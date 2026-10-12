# 人脸基线扫描工具 v1.2

多选 NAS 文件夹，每个所选目录就是一个独立图库。使用固定 OFIQ 保留 Top K，自动挑选合格基线或保留手动锁定。
现有 Figma Make 三页设计已接上 FastAPI、SQLite 和串行扫描 worker。

## 使用

NAS 网页：`http://192.168.31.201:33081/`；本机 API：`http://127.0.0.1:33081/api`。
API 文档 `/docs`。网页提供文件夹多选器，目前浏览范围为 `/vol3/1000/Picture/YY/人物`，已选择该目录的全部子目录。每个选中目录单独作为一个图库，递归读取 JPG/JPEG/PNG。
只在网页或 API 手动触发时扫描；没有定时扫描、实时监听或开机自动续扫。新增子目录不会自动选入。

默认 K=5、总分门槛 60。Top K 优先保留通过基线质量检查的单人照片，再以 OFIQ 总分排序；不足 K 时可包含低质量单人照。自动基线须通过全部检查。
无脸、多人、解码/评分失败的照片不可选。手动允许锁定低分单人照片，会提示质量不足。
锁定图掉榜也继续保留；取消锁定立即自动选择。所有原文件保留。

仅当前基线加 `基线__` 前缀，切换时旧图恢复原名；重名加稳定照片 ID，绝不覆盖。
Top K 和手选图使用专属 XMP-fb 字段记录身份、原名、OFIQ 原生/归一分项、引擎版本、
合格状态和活动标记。退出候选清除活动标记，评分保留。原拍摄信息及压缩图像内容保留。

## 扫描与恢复

每次枚举文件，两次 size/mtime 检查相隔 10 秒。完整解码后按 RGB 像素 SHA256
识别内容，评分缓存键为图像内容与固定引擎、检测模型及预处理版本。版本不匹配会重新评估，旧缓存仍保留。同图只占一候选；相近连拍和角度
多样性不属于 v1。改名利用文件身份保留 ID；元数据变化经像素散列确认，不重新评分。
处理期间文件变化则不接受评分，下一次重试。

SQLite 保存人员、文件档案、任务、基线版本和文件操作日志。快照、旧图恢复、新图
改名、元数据写回依次执行，失败保留 pending 状态；网页显示原因，后续扫描或操作
继续修复。元数据先在同目录临时副本写入并核对像素和源文件状态，再替换。
Linux renameat2 的 RENAME_NOREPLACE 保证原子改名不覆盖其他文件。
服务只运行一个 Uvicorn worker；扫描、锁定、取消锁定和写回共用互斥锁。
重复扫描合并；不同范围在已有单人扫描运行时排队，串行执行。服务中断后保留档案与未完成操作；下一次手动扫描继续处理。

基线选择或内容/锁定模式变化会记录新版本，快照保存在私有目录。v1 不接生图任务，
不提供下游版本协议，也不实时监听或发送外部通知。

## 基线质量复核

全图使用固定 OpenCV Zoo YuNet 2023mar，在 640/1280 两个尺度检测并合并重复框。检测置信度 0.6，不能确认单人、检测到多人或两次检测位置不一致时均不能入选。通过全图复核后，临时裁切人脸及周边供 OFIQ 评分；原照片、缩略图和历史快照仍保存完整原图，不写入裁切内容。网页绿色框标明实际评分人脸。单人复核与目录命名不构成人物身份识别。

自动基线的初始检查门槛：OFIQ 总分达到配置值、Sharpness ≥70、原始眼间距 ≥70px、人脸宽高 ≥120px、EyesVisible ≥80、EyesOpen ≥70、FaceOcclusionPrevention ≥80、Yaw/Pitch/Roll ≥80、IlluminationUniformity ≥50；任何必需指标无法评估也不自动选择。它们是本工具的初始适用性规则，须经实际图库继续校准。低质量单人照可手动锁定并显示具体原因；多人照不能通过锁定绕过复核。

OFIQ UnifiedQualityScore 来自独立模型，分项用于检查适用性，不是总分的加权解释。升级规则时先撤下尚未复核的自动基线并恢复旧原名，保留锁定 ID、所有历史快照和评分缓存；重新扫描后通过新版单人复核的锁定图继续生效，不能通过的锁定记录仍保留但不作为当前基线。升级不会自行提交扫描；本次修复人工提交图库复核任务。

YuNet 模型 SHA256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`，来源固定 OpenCV Zoo 提交 `47534e27c9851bb1128ccc0102f1145e27f23f98`，MIT 许可随模型保存在 `/opt/ofiq/yunet/LICENSE`。API 照片字段包含 `eligible`、`qualified`、`qualityIssues`、`assessmentFace` 和 `imageSize`，网页与元数据使用同一后端资格判断。

## 目录与部署

- 源码 `/home/yuwk/code/face-baseline`；设计来自
  [Figma Make](https://www.figma.com/make/sf4QM4kgvGPQa9G9nshzx2/Untitled)。
- 正式 Compose `/vol2/1000/Docker/stacks/utilities/compose.yaml`，沿用 `tool_net`。
- 私有运行目录 `/vol2/1000/Docker/face-baseline/data`：SQLite、缩略图、历史快照。
- 固定引擎下载/构建材料 `/vol2/1000/Docker/face-baseline/engine`，不进入源码仓库。
- 旧 cron 入口和包装已移除；原运行记录保留。

固定官方 eu-LISA 包含 OFIQ **1.0.3** 和模型；包 SHA256
`c8996f37246731d7bd195697da04542b97cdf4e34a5d43ea1ab6a3138c4620ce`。
不是自动跟随最新版本。运行器检查二进制实际版本，并使用一次初始化的原生引擎实例；
评分返回精确人脸数，不以 SingleFacePresent 归一分数代替数量判断。
官方资料：[OFIQ](https://github.com/BSI-OFIQ/OFIQ-Project)、
[构建和官方发布包](https://github.com/BSI-OFIQ/OFIQ-Project/blob/main/BUILD.md)。
许可随镜像保存在 `/opt/ofiq/LICENSE.md`。

```sh
python3 scripts/prepare-engine.py /vol2/1000/Docker/face-baseline/engine
python3 scripts/prepare-detector.py /vol2/1000/Docker/face-baseline/engine/yunet
cd web
npm ci
npx tsc --noEmit
npm run build
cd ..
docker buildx build --load --build-context ofiq=/vol2/1000/Docker/face-baseline/engine -t local/face-baseline:1.2.0 .
docker compose -p utilities -f /vol2/1000/Docker/stacks/utilities/compose.yaml up -d --no-deps face-baseline
```

图库挂载使用相同宿主/容器路径。图库设置保存 `folders` 数组。文件夹多选支持不同层级及多个已挂载位置；父子目录不能同时选入，避免重复归类。
更换所选目录不删除档案；重新选择同一路径保留人物/照片 ID、锁定和历史。旧版单一 `root` 自动迁移为原有目录列表。
需要增加可选位置时，仅修改此服务的媒体挂载和 `FACE_BASELINE_LIBRARY_BASES`（JSON 路径数组），保持宿主/容器路径一致。容器身份 1000:1001、只读根文件系统，数据和图库可写。
端口仅绑定 NAS 局域网和 loopback；没有新增公网或 Tailnet 入口。

本地开发：Python venv 安装 `requirements.txt`，`FACE_BASELINE_DATA` 指定私有目录，
本地 API 调试启动 `uvicorn backend.app:create_app --factory --port 8080`。原生引擎需在 Ubuntu 24.04 容器内运行，
不能把预编译包直接用于 NAS 的旧 glibc。前端 Vite 的 `/api` 代理默认连接已部署的 33081 服务。

## 验收

`python -m pytest tests -q` 在临时图库使用可控评分夹具和真实 ExifTool 验证业务规则，
不把夹具分数用于正式服务。部署验收覆盖旧图库迁移、只扫描所选目录、文件夹多选和保存，以及桌面/窄屏检查。
既有真实 OFIQ 单人/无脸/多人评分、真实单人扫描与增量重扫已验证。验收结果见 `VALIDATION.md`。
