这里放 GPT-SoVITS 训练出来的东西，脚本会自动找。

    voice\
      weights\   放两个权重文件
                   xxx_e10_s100.pth     <- SoVITS
                   xxx-e15.ckpt         <- GPT
      ref\       放参考音频（3~10 秒，干净无 BGM、无混响）
                   normal.wav  + normal.txt    常态
                   happy.wav   + happy.txt     开心（可选）
                   shy.wav     + shy.txt       害羞/慌（可选）
                   sad.wav     + sad.txt       低落（可选）

`xxx.txt` 里写这段音频说的原话（日语），合成时会作为参考文本用。
没有对应情绪文件就退回 normal，不会报错。

放好以后：
  1. 先把 GPT-SoVITS 的 api_v2.py 跑起来（默认 9880 端口）
  2. 双击 tools\tts.bat → 选 2，脚本会自动扫 weights\
  3. 重启 AstrBot

几个提醒：

- 权重文件名不用改，脚本按后缀认：.pth 当 SoVITS，.ckpt 当 GPT。
- 如果某个文件夹里有多个同后缀文件，脚本会列出来让你选，不会乱挑。
- 参考音频挑情绪平稳、语速偏慢的一段。笑场、拖尾音、带背景音乐的都不合适，
  那些特点会被复制到每一句话上。
- 情绪参考音频是从训练集里挑的原声，不是另外录的。
- 别把整个 GPT-SoVITS 程序塞进这里，只放训练产物。程序放哪都行，只要服务能起。
