语音权重放这里（不进 git，走 GitHub Releases 下载）

需要的两个文件（文件名必须和下面一致，否则改 cmd_config.json 里的路径）：

  GPT 权重   11g-miyako-e40.ckpt       约 148MB
  SoVITS 权重 11g-miyako_e40_s3480.pth  约 165MB

来源：仓库 Releases 页面 → 最新版本 → Assets。
架构要求：GPT-SoVITS v2ProPlus（20250604）。其他架构加载会报错。

参考音在 ../ref/，仓库自带，不用另外准备：
  normal / happy / shy / sad 各一对 .wav + .txt
  换参考音会影响语气，不影响音色。
