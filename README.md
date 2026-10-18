# clawd-mv

**作者：绘梨衣Yojen** · **MIT 许可**：免费使用、修改、再分发，保留署名即可。

一个把「给一首歌做一支手绘动画 MV」变成可执行流程的技能包，给 AI 直接读。
基于 [ClaudeAnimationBase](https://github.com/JohnHeibel/ClaudeAnimationBase)（p5.js + p5.brush + Clawd 小螃蟹）。

## 里面有什么

- `SKILL.md` —— 完整工作流：分镜铁律、逐句对齐、多角色排布、渲染与故障速查
- `scripts/render.py` —— 无头渲染器（Edge + CDP，帧序列 / 接触表 / 编码）

## 怎么用

把这个文件夹放进 AI 的技能目录（例如 `~/.dsh/skills/clawd-mv/`），
或者直接把 `SKILL.md` 丢给一个会写代码的模型，让它照做。

```powershell
python scripts/render.py --url "file:///<你的项目>/studio.html?render" --frames --range=0:120 --fps=24 --out=out/frames
python scripts/render.py --encode --fps=24 --audio=assets/song.m4a --out=out/MV.mp4
```

## 许可

MIT。署名 **绘梨衣Yojen** 即可自由使用与修改。
