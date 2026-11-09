# 鲸鱼娘皮肤 / Whale-girl skin

## 授权 / License

本目录下的所有图片（`*.png` 以及 `source/` 里的原图）按
**[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)** 授权：
可以转载、修改，但必须**署名**、**不能商用**、衍生作品要用**相同的授权**。
这和仓库代码的 MIT 授权是分开的。

All images in this directory (`*.png` and the original sheets in `source/`) are licensed under
**[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)**:
attribution required, non-commercial only, share-alike. This is separate from the MIT license of the code.

## 署名 / Credits

形象是 DeepSeek 社区的**同人**拟人「鲸鱼娘 / 蓝色大肥鱼」（女仆 Q 版），
**不是 DeepSeek 官方角色，本项目与 DeepSeek 无任何关联。**

- 原始角色形象 / Original character design：**上善无形（上善）**
- 女仆形象二次设计 / Maid redesign：**ZipZipPipe**
- 设定图来源 / Reference sheets：<https://github.com/xiaoweigen/deepseek-dafeiyu-assets>（CC BY-NC-SA 4.0）

这里的精灵表由 AI 绘图工具参照上述设定图生成，再用 `tools/slice_sheet.py` 切成各个动作。

The sprite sheets here were generated with an AI image tool using the reference sheets above,
then sliced into frames with `tools/slice_sheet.py`. This is fan art of a community character;
it is not affiliated with or endorsed by DeepSeek.

## 文件 / Files

| 原图 `source/` | 切出来的 |
|---|---|
| `sheet_source.png` | 基础表情：idle blink talk alarm qr happy sleep eat oops |
| `move_source.png` | 移动：walk stroll hop roll dizzy |
| `actions_source.png` | 小动作：stretch yawn look wave fish sit dance dust |
| `menu_icons*_source.png` | 右键菜单泡泡图标 `menu_*.png`（每个都有 `_hover` 大一号） |

重新切（几张图里角色 / 图标画得大小不一，用小数倍缩放对齐）：

```
python tools/slice_sheet.py skins/whale/source/sheet_source.png --scale 3
python tools/slice_sheet.py skins/whale/source/move_source.png --scale 3.1 --names walk_1,walk_2,walk_3,walk_4,stroll_1,stroll_2,stroll_3,stroll_4,hop_1,hop_2,roll_1,dizzy_1
python tools/slice_sheet.py skins/whale/source/actions_source.png --scale 3.2 --names stretch_1,yawn_1,look_1,wave_1,wave_2,fish_1,fish_2,sit_1,dance_1,dance_2,dust_1,dust_2
python tools/slice_sheet.py skins/whale/source/menu_icons_source.png --cols 7 --rows 1 --scale 6 --names menu_msg,menu_work,menu_perf,menu_daily,menu_qr,menu_home,menu_exit
python tools/slice_sheet.py skins/whale/source/menu_icons2_source.png --cols 8 --rows 1 --scale 4.45 --names menu_home2,menu_gear,menu_start,menu_pause,menu_music,menu_exit2,menu_play,menu_back
python tools/slice_sheet.py skins/whale/source/menu_icons3_source.png --cols 4 --rows 4 --scale 5.11 --names menu_feed,menu_status,menu_job,menu_dnd,menu_refresh,menu_calendar,menu_today,menu_chat,menu_alarm,menu_timer,menu_gift,menu_trophy,menu_outfit,menu_sleep,menu_sound,menu_mute
python tools/slice_sheet.py skins/whale/source/menu_icons4_source.png --cols 4 --rows 4 --scale 4.93 --names menu_more,menu_prev,menu_next,menu_ok,menu_close,menu_add,menu_delete,menu_search,menu_folder,menu_log,menu_power,menu_save,menu_team,menu_help,menu_fish,menu_dice
python tools/slice_sheet.py skins/whale/source/menu_icons5_source.png --cols 4 --rows 3 --scale 5.57 --names menu_interact,menu_home,menu_chase,menu_back,menu_prev,menu_next,menu_fish,menu_ball,menu_music,menu_feed,menu_status,menu_trick
python tools/slice_sheet.py skins/whale/source/menu_icons6_source.png --cols 4 --rows 3 --scale 5.32 --names menu_msg,menu_pin,menu_bell,menu_mute,menu_work,menu_perf,menu_daily,menu_qr,menu_job,menu_clock,menu_flag,menu_search
```

图标的悬停版：同样的命令，`--scale` 分别换成 5 / 3.71 / 4.26 / 4.11 / 4.64 / 4.43，名字加 `_hover` 后缀。
后两张（icons5 / icons6）是第二批，重画了前面几张里的同名图标，**要最后切**，才会覆盖掉旧的。
缩放倍数 = 这张图里泡泡的直径 ÷ 49（第一张 292 像素对应 6 倍）。
