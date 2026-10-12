"""Convert the verified official FaceQnet v1 model to ONNX for CPU serving."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path

os.environ['OMP_NUM_THREADS'] = '2'
os.environ['TF_NUM_INTRAOP_THREADS'] = '2'
os.environ['TF_NUM_INTEROP_THREADS'] = '1'


def convert_mtcnn(symbol, params, output, stage):
    """Export the fixed MTCNN inference operators with NCHW PReLU slopes."""
    import mxnet as mx
    import onnx
    from onnx import helper, numpy_helper, TensorProto

    graph = json.loads(symbol.read_text())
    weights = {key.split(':', 1)[1]:value.asnumpy() for key,value in mx.nd.load(str(params)).items()}
    nodes, ranks = [], {'data':4}
    for item in graph['nodes']:
        name, op = item['name'], item['op']
        if op == 'null':
            continue
        inputs = [graph['nodes'][index[0]]['name'] for index in item['inputs']]
        attrs = item['param']
        pair = lambda key: list(ast.literal_eval(attrs[key]))
        if op == 'Convolution':
            nodes.append(helper.make_node('Conv', inputs, [name], name=name,
                         kernel_shape=pair('kernel'), strides=pair('stride'), pads=pair('pad')*2,
                         dilations=pair('dilate'), group=int(attrs['num_group'])))
            ranks[name] = 4
        elif op == 'Pooling':
            nodes.append(helper.make_node('MaxPool', inputs, [name], name=name,
                         kernel_shape=pair('kernel'), strides=pair('stride'), pads=pair('pad')*2,
                         ceil_mode=int(attrs['pooling_convention']=='full')))
            ranks[name] = 4
        elif op == 'LeakyReLU':
            rank = ranks[inputs[0]]
            weights[inputs[1]] = weights[inputs[1]].reshape((-1,) + (1,)*(rank-2))
            nodes.append(helper.make_node('PRelu', inputs, [name], name=name))
            ranks[name] = rank
        elif op == 'FullyConnected':
            flat = name + '_flat'
            nodes.append(helper.make_node('Flatten', [inputs[0]], [flat], name=flat, axis=1))
            nodes.append(helper.make_node('Gemm', [flat,*inputs[1:]], [name], name=name, transB=1))
            ranks[name] = 2
        elif op in ('SoftmaxActivation', 'SoftmaxOutput'):
            nodes.append(helper.make_node('Softmax', inputs[:1], [name], name=name, axis=1))
            ranks[name] = ranks[inputs[0]]
        else:
            raise ValueError(f'Unsupported MTCNN operator: {op}')
    size = {1:64, 2:24, 3:48}[stage]
    shape = [1,3,'height','width'] if stage == 1 else ['batch',3,size,size]
    outputs = []
    for index in graph['heads']:
        name = graph['nodes'][index[0]]['name']
        head = next(node for node in graph['nodes'] if node['name']==name)
        features = 2 if name=='prob1' else int(head['param']['num_filter' if stage==1 else 'num_hidden'])
        output_shape = [1,features,'out_height','out_width'] if stage==1 else ['batch',features]
        outputs.append(helper.make_tensor_value_info(name,TensorProto.FLOAT,output_shape))
    exported = helper.make_graph(nodes,f'MTCNN-det{stage}',[helper.make_tensor_value_info('data',TensorProto.FLOAT,shape)],outputs,
                                 [numpy_helper.from_array(value,name) for name,value in weights.items()])
    model = helper.make_model(exported,opset_imports=[helper.make_opsetid('',13)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model,str(output))

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--checkpoint', type=Path)
    p.add_argument('--mtcnn', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--only-detector', action='store_true')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.only_detector:
        assert hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() == '90e86f52f9c802a10576d911f9305c18f15b853fe4a206a02c5f5600baa06726'
        import tensorflow as tf
        import tf2onnx
        model = tf.keras.models.load_model(args.checkpoint, compile=False)
        signature = [tf.TensorSpec([None, 224, 224, 3], tf.float32, name='faces')]
        @tf.function(input_signature=signature)
        def predict(faces):
            return model(faces, training=False)
        tf2onnx.convert.from_function(predict, input_signature=signature, opset=13, output_path=str(args.output / 'faceqnet-v1.onnx'))
    import numpy as np
    np.bool = bool  # MXNet 1.9's NumPy compatibility.
    mtcnn = args.output / 'mtcnn'
    mtcnn.mkdir(exist_ok=True)
    inputs = {}
    for i in (1, 2, 3):
        symbol, params = args.mtcnn / f'det{i}-symbol.json', args.mtcnn / f'det{i}-0001.params'
        convert_mtcnn(symbol,params,mtcnn / f'det{i}.onnx',i)
        inputs.update({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (symbol, params)})
    (args.output / 'MTCNN-LICENSE').write_text((args.mtcnn.parent / 'license.txt').read_text())
    manifest = dict(source='https://github.com/uam-biometrics/FaceQnet/releases/download/v1.0/FaceQnet_v1.h5',
                    checkpointSha256='90e86f52f9c802a10576d911f9305c18f15b853fe4a206a02c5f5600baa06726',
                    mtcnnSource='https://github.com/pterhoer/FaceImageQuality/tree/611296605db57b8d50518fd5911d5111eeb52747/insightface/mtcnn-model',
                    mtcnnInputs=inputs,
                    files={str(f.relative_to(args.output)):hashlib.sha256(f.read_bytes()).hexdigest() for f in args.output.rglob('*') if f.is_file() and f.name != 'manifest.json'})
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
