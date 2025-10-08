import requests

# IPTV接口地址
url = "http://10.255.9.200/IPTV_EPG/Channel/GetChannelsList?platform=IPTV%2B&includePlaybill=0&operator=1&videoType=1&version=YYS.5.4.1.266.6.HNDXIPTV.0.0_Release_ZTE_4K&includeSubData=0&sortType=weight&rootCategoryId="

# 需要的分类ID（顺序保留）
target_categories = {
    "1000009": "超高清",
    "1000302": "省内",
    "1000003": "央视",
    "1000004": "卫视",
    "1000008": "风尚付费",
    "8ca5fb111c664b0f84100e56fd292aae": "芒果影视付费",
    "1000051": "其它",
}

# 请求接口
resp = requests.get(url, timeout=10)
data = resp.json()
channels = data.get("channelList", [])

# 初始化两个列表
m3u_multicast = ["#EXTM3U"]
m3u_unicast = ["#EXTM3U"]

for ch in channels:
    cat_ids = ch.get("categoryId", "").split("|")

    # 只保留 target_categories 中出现的第一个匹配分类
    matched_first = next((target_categories[cid] for cid in cat_ids if cid in target_categories), None)
    if not matched_first:
        continue

    channel_number = ch.get("channelNumber", "")
    channel_name = ch.get("channelName", "")
    logo = ch.get("logoImg", "")
    play_url = ch.get("playUrl", "")
    backup_url = ch.get("backupPlayUrl", "")
    group_title = matched_first

    # ===== 组播部分 =====
    if play_url.startswith("rtp://"):
        ip_port = play_url.replace("rtp://", "")
        # 兼容APTV的单播回放地址
        catchup_source = ""
        if backup_url and backup_url.startswith("http"):
            catchup_source = f' catchup-source="{backup_url}?starttime={{utc:YmdHMS}}&endtime={{utcend:YmdHMS}}"'
        extinf = (
            f'#EXTINF:-1 tvg-id="{channel_number}" tvg-logo="{logo}" '
            f'group-title="{group_title}"{catchup_source},{channel_name}'
        )
        m3u_multicast.append(extinf)
        # 需自行修改组播转单播局域网实现地址
        m3u_multicast.append(f"http://192.168.31.1:8022/udp/{ip_port}")

    # ===== 单播部分 =====
    if backup_url and backup_url.startswith("http"):
        full_unicast_url = f"{backup_url}?zte_offset=0&ispcode=2&starttime="
        catchup_source = f'{backup_url}?starttime={{utc:YmdHMS}}&endtime={{utcend:YmdHMS}}'
        extinf_u = (
            f'#EXTINF:-1 tvg-id="{channel_number}" tvg-logo="{logo}" '
            f'group-title="{group_title}" catchup-source="{catchup_source}",{channel_name}'
        )
        m3u_unicast.append(extinf_u)
        m3u_unicast.append(full_unicast_url)

# ===== 写入文件 =====
output_multicast = r"C:\Users\LYLUs\Downloads\湖南电信IPTV组播.m3u"
output_unicast = r"C:\Users\LYLUs\Downloads\湖南电信IPTV单播.m3u"

with open(output_multicast, "w", encoding="utf-8") as f1:
    f1.write("\n".join(m3u_multicast))
with open(output_unicast, "w", encoding="utf-8") as f2:
    f2.write("\n".join(m3u_unicast))

print(f"已生成组播列表：{output_multicast}")
print(f"已生成单播列表：{output_unicast}")
