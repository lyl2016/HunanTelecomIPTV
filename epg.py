import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os
import glob
import io
import gzip
import time

# ====== IPTV频道列表接口 ======
CHANNEL_URL = (
    "http://10.255.9.200/IPTV_EPG/Channel/GetChannelsList"
    "?platform=IPTV%2B&includePlaybill=0&operator=1&videoType=1"
    "&version=YYS.5.4.1.266.6.HNDXIPTV.0.0_Release_ZTE_4K"
    "&includeSubData=0&sortType=weight&rootCategoryId="
)

# ====== EPG API 理论可以往前拿到15天的EPG 但无法回看那么长 没有意义 ======
EPG_API = (
    "http://10.255.0.110/mgtv_hndx/BasicIndex/GetPlaybill"
    "?BeforeDay=7&AfterDay=5&OutputType=json&Mode=relative&VideoId={video_id}"
)

# ====== 缓存参数 ======
CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_LIFETIME = timedelta(hours=12)
CACHE_REFRESH_BEFORE_EXPIRY = timedelta(hours=3)
MAX_CACHE_FILES = 3
AUTO_REFRESH_INTERVAL = 3600  # 每小时自动刷新一次


# ====== 自动清理旧缓存，只保留最近三份 ======
def cleanup_old_caches():
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "epg_cache_*.xml")), reverse=True)
    if len(files) > MAX_CACHE_FILES:
        for f in files[MAX_CACHE_FILES:]:
            try:
                os.remove(f)
                print(f"已删除旧缓存: {os.path.basename(f)}")
            except Exception as e:
                print(f"删除旧缓存失败 {f}: {e}")


# ====== 生成EPG XML ======
def generate_epg_xml():
    print("正在获取频道列表...")
    resp = requests.get(CHANNEL_URL, timeout=10)
    data = resp.json()
    channels = data.get("channelList", [])

    tv = ET.Element("tv", {"generator-info-name": "HNDX-IPTV-EPG"})

    for ch in channels:
        channel_name = ch.get("channelName", "")
        channel_number = ch.get("channelNumber", "")
        hwCms3Id = ch.get("hwCms3Id", "")
        logo = ch.get("logoImg", "")
        if not hwCms3Id:
            continue

        ch_node = ET.SubElement(tv, "channel", {"id": channel_number})
        ET.SubElement(ch_node, "display-name").text = channel_name
        if logo:
            ET.SubElement(ch_node, "icon", {"src": logo})

        try:
            epg_resp = requests.get(EPG_API.format(video_id=hwCms3Id), timeout=10)
            epg_data = epg_resp.json()
        except Exception as e:
            print(f"获取失败：{channel_name} - {e}")
            continue

        for day_block in epg_data.get("day", []):
            day_str = str(day_block.get("day", ""))
            if not day_str:
                continue

            for item in day_block.get("item", []):
                title = item.get("text", "未命名节目")
                begin = item.get("begin", "000000")
                duration = int(item.get("time_len", "0"))

                start_dt = datetime.strptime(day_str + begin, "%Y%m%d%H%M%S")
                stop_dt = start_dt + timedelta(seconds=duration)

                start_str = start_dt.strftime("%Y%m%d%H%M%S +0800")
                stop_str = stop_dt.strftime("%Y%m%d%H%M%S +0800")

                prog_node = ET.SubElement(tv, "programme", {
                    "start": start_str,
                    "stop": stop_str,
                    "channel": channel_number
                })
                ET.SubElement(prog_node, "title", {"lang": "zh"}).text = title

    tree = ET.ElementTree(tv)
    ET.indent(tree, space="  ", level=0)
    xml_io = io.BytesIO()
    tree.write(xml_io, encoding="utf-8", xml_declaration=True)
    xml_bytes = xml_io.getvalue()

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    cache_file = os.path.join(CACHE_DIR, f"epg_cache_{timestamp}.xml")
    with open(cache_file, "wb") as f:
        f.write(xml_bytes)
    print(f"新缓存生成: {cache_file}")

    cleanup_old_caches()
    return xml_bytes


# ====== 缓存管理 ======
def get_latest_cache():
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "epg_cache_*.xml")), reverse=True)
    if not files:
        return None, None
    latest = files[0]
    ts_str = os.path.splitext(os.path.basename(latest))[0].replace("epg_cache_", "")
    try:
        ts = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
        return latest, ts
    except ValueError:
        return None, None


def get_cache_status():
    cache_file, ts = get_latest_cache()
    if not cache_file:
        return None, None, "no_cache"

    age = datetime.now() - ts
    remaining = CACHE_LIFETIME - age

    if age < CACHE_LIFETIME:
        if remaining <= CACHE_REFRESH_BEFORE_EXPIRY:
            return cache_file, remaining, "stale_soon"
        return cache_file, remaining, "valid"
    else:
        return cache_file, timedelta(0), "expired"


def async_refresh_cache():
    def worker():
        try:
            print("异步刷新缓存开始...")
            generate_epg_xml()
            print("异步刷新缓存完成。")
        except Exception as e:
            print(f"异步刷新失败: {e}")
    threading.Thread(target=worker, daemon=True).start()


# ====== 每小时自动刷新线程 ======
def auto_refresh_thread():
    while True:
        print("每小时自动刷新EPG缓存...")
        try:
            generate_epg_xml()
        except Exception as e:
            print(f"自动刷新失败: {e}")
        time.sleep(AUTO_REFRESH_INTERVAL)


# ====== HTTP请求处理 ======
class EPGRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/epg"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        cache_file, remaining, status = get_cache_status()

        if status == "no_cache":
            xml_bytes = generate_epg_xml()
        elif status == "valid":
            with open(cache_file, "rb") as f:
                xml_bytes = f.read()
        elif status == "stale_soon":
            with open(cache_file, "rb") as f:
                xml_bytes = f.read()
            async_refresh_cache()
        else:
            xml_bytes = generate_epg_xml()

        # === gzip压缩输出 ===
        accept_encoding = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept_encoding.lower():
            xml_bytes = gzip.compress(xml_bytes, compresslevel=6)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(200)

        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(xml_bytes)


# ====== 启动HTTP服务 ======
def run_server(host="127.0.0.1", port=7080):
    print(f"EPG服务启动: http://{host}:{port}/epg")
    threading.Thread(target=auto_refresh_thread, daemon=True).start()
    httpd = HTTPServer((host, port), EPGRequestHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    run_server()
