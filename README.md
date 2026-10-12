# 人脸基线扫描工具 v1

用固定 OFIQ 评分图库，按人物保留 Top K，自动挑选合格基线或保留手动锁定。
现有 Figma Make 三页设计已接上 FastAPI、SQLite 和串行扫描 worker。

## 使用

NAS 网页：`http://192.168.31.201:33081/`；本机 API：`http://127.0.0.1:33081/api`。
API 文档 `/docs`。默认图库 `/vol3/1000/Picture/YY/人物`，直接子目录为人物，
递归读取 JPG/JPEG/PNG。每天 03:00 Asia/Taipei 由 cron 提交任务；也可网页扫描全部或单人。

默认 K=5、合格门槛 60。Top K 可包含低分，自动基线须为合格单人照片。
无脸、多人、解码/评分失败的照片不可选。手动允许锁定低分单人照片，会提示质量不足。
锁定图掉榜也继续保留；取消锁定立即自动选择。所有原文件保留。

仅当前基线加 `基线__` 前缀，切换时旧图恢复原名；重名加稳定照片 ID，绝不覆盖。
Top K 和手选图使用专属 XMP-fb 字段记录身份、原名、OFIQ 原生/归一分项、引擎版本、
合格状态和活动标记。退出候选清除活动标记，评分保留。原拍摄信息及压缩图像内容保留。

## 扫描与恢复

每次枚举文件，两次 size/mtime 检查相隔 10 秒。完整解码后按 RGB 像素 SHA256
识别内容，评分缓存键为图像内容与固定引擎版本。同图只占一候选；相近连拍和角度
多样性不属于 v1。改名利用文件身份保留 ID；元数据变化经像素散列确认，不重新评分。
处理期间文件变化则不接受评分，下一次重试。

SQLite 保存人员、文件档案、任务、基线版本和文件操作日志。快照、旧图恢复、新图
改名、元数据写回依次执行，失败保留 pending 状态；网页显示原因，后续扫描或操作
继续修复。元数据先在同目录临时副本写入并核对像素和源文件状态，再替换。
Linux renameat2 的 RENAME_NOREPLACE 保证原子改名不覆盖其他文件。
服务只运行一个 Uvicorn worker；扫描、锁定、取消锁定和写回共用互斥锁。
重复扫描合并；不同范围在已有单人扫描运行时排队，串行执行。服务中断后续跑档案。

基线选择或内容/锁定模式变化会记录新版本，快照保存在私有目录。v1 不接生图任务，
不提供下游版本协议，也不实时监听或发送外部通知。

## 目录与部署

- 源码 `/home/yuwk/code/face-baseline`；设计来自
  [Figma Make](https://www.figma.com/make/sf4QM4kgvGPQa9G9nshzx2/Untitled)。
- 正式 Compose `/vol2/1000/Docker/stacks/utilities/compose.yaml`，沿用 `tool_net`。
- 私有运行目录 `/vol2/1000/Docker/face-baseline/data`：SQLite、缩略图、历史快照。
- 固定引擎下载/构建材料 `/vol2/1000/Docker/face-baseline/engine`，不进入源码仓库。
- cron 包装源码在 `nas-cron-jobs/face-baseline`，部署脚本在 `/home/yuwk/cron/scripts`。

固定官方 eu-LISA 包含 OFIQ **1.0.3** 和模型；包 SHA256
`c8996f37246731d7bd195697da04542b97cdf4e34a5d43ea1ab6a3138c4620ce`。
不是自动跟随最新版本。运行器检查二进制实际版本，并使用一次初始化的原生引擎实例；
评分返回精确人脸数，不以 SingleFacePresent 归一分数代替数量判断。
官方资料：[OFIQ](https://github.com/BSI-OFIQ/OFIQ-Project)、
[构建和官方发布包](https://github.com/BSI-OFIQ/OFIQ-Project/blob/main/BUILD.md)。
许可随镜像保存在 `/opt/ofiq/LICENSE.md`。

```sh
python3 scripts/prepare-engine.py /vol2/1000/Docker/face-baseline/engine
cd web
npm ci
npx tsc --noEmit
npm run build
cd ..
docker buildx build --load --build-context ofiq=/vol2/1000/Docker/face-baseline/engine -t local/face-baseline:1.0.0 .
docker compose -p utilities -f /vol2/1000/Docker/stacks/utilities/compose.yaml up -d --no-deps face-baseline
```

图库挂载使用相同宿主/容器路径。网页更换根目录必须指向实际可见的挂载目录；新增
其他媒体挂载只修改此服务。容器身份 1000:1001、只读根文件系统，数据和图库可写。
端口仅绑定 NAS 局域网和 loopback；没有新增公网或 Tailnet 入口。

本地开发：Python venv 安装 `requirements.txt`，`FACE_BASELINE_DATA` 指定私有目录，
本地 API 调试启动 `uvicorn backend.app:create_app --factory --port 8080`。原生引擎需在 Ubuntu 24.04 容器内运行，
不能把预编译包直接用于 NAS 的旧 glibc。前端 Vite 的 `/api` 代理默认连接已部署的 33081 服务。

## 验收

`python -m pytest tests -q` 在临时图库使用可控评分夹具和真实 ExifTool 验证业务规则，
不把夹具分数用于正式服务。部署验收另外执行真实 OFIQ 单人/无脸/多人评分、真实
图库单人扫描和增量重扫，以及网页桌面/窄屏检查。验收结果见 `VALIDATION.md`。
