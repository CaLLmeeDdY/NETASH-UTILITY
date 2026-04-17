from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import speedtest
import asyncio
import uvicorn
import subprocess
import re
import socket

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get_index():
    return FileResponse("index.html")

# --- SPEEDTEST MODULE ---
def init_speedtest():
    st = speedtest.Speedtest(secure=False) 
    st.get_best_server()
    return st

@app.websocket("/ws/speedtest")
async def ws_speedtest(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        await websocket.send_json({"status": "🔗 Connected. Finding optimal server...", "data": None})
        st = await loop.run_in_executor(None, init_speedtest)
        ping_val = st.results.ping
        isp_val = st.results.client.get('isp', 'Unknown ISP')
        
        await websocket.send_json({
            "status": "✅ Server found! Testing Download Capacity...", 
            "data": {"ping": round(ping_val, 1), "isp": isp_val}
        })
        
        dl_bps = await loop.run_in_executor(None, st.download)
        await websocket.send_json({
            "status": "⬇️ Download complete. Testing Upload Capacity...", 
            "data": {"download": round(dl_bps / 1_000_000, 2)}
        })
        
        ul_bps = await loop.run_in_executor(None, st.upload)
        await websocket.send_json({
            "status": "✅ Diagnostics Complete.", 
            "data": {"upload": round(ul_bps / 1_000_000, 2)}
        })
    except Exception as e:
        await websocket.send_json({"status": f"⚠️ Error: {str(e)}", "data": None})
    finally:
        await websocket.close()


# --- PING PULSE MODULE ---
def ping_host(host):
    try:
        output = subprocess.check_output(["ping", "-c", "1", "-W", "1", host], universal_newlines=True)
        match = re.search(r'time=([\d.]+) ms', output)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None

@app.websocket("/ws/ping")
async def ws_ping(websocket: WebSocket):
    await websocket.accept()
    try:
        target_ip = await websocket.receive_text() 
        while True:
            latency = ping_host(target_ip)
            if latency is not None:
                await websocket.send_json({"status": "success", "ping": latency})
            else:
                await websocket.send_json({"status": "timeout", "ping": 0})
            await asyncio.sleep(1) 
    except WebSocketDisconnect:
        pass


# --- NETWORK SCANNER MODULE ---
def get_local_subnet():
    """Finds the local IP address of the host machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        base_ip = ip.rsplit('.', 1)[0]
        return ip, base_ip
    except:
        return "127.0.0.1", "127.0.0.1"
    finally:
        s.close()

async def async_ping_sweep(base_ip):
    """Silently pings 254 IP addresses at the same time."""
    tasks = []
    for i in range(1, 255):
        ip = f"{base_ip}.{i}"
        proc = await asyncio.create_subprocess_exec(
            'ping', '-c', '1', '-W', '1', ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        tasks.append(proc.wait())
    await asyncio.gather(*tasks)

def get_arp_devices():
    """Reads the Linux ARP cache, filtering out IPv6."""
    devices = []
    try:
        output = subprocess.check_output(["ip", "neigh"], universal_newlines=True)
        for line in output.split('\n'):
            parts = line.split()
            # Ensure it's an IPv4 address (contains '.') and has a MAC address
            if len(parts) >= 5 and "lladdr" in line and "." in parts[0]:
                ip = parts[0]
                mac_index = parts.index("lladdr") + 1
                if mac_index < len(parts):
                    mac = parts[mac_index].upper()
                    state = parts[-1].upper()
                    if state in ["REACHABLE", "STALE", "DELAY"]:
                        devices.append({"ip": ip, "mac": mac})
    except Exception:
        pass
    return devices

@app.websocket("/ws/scanner")
async def ws_scanner(websocket: WebSocket):
    await websocket.accept()
    try:
        my_ip, base_ip = get_local_subnet()
        await websocket.send_json({"status": f"🔍 Detected network interface at {my_ip}", "data": None})
        
        await websocket.send_json({"status": f"📡 Broadcasting to {base_ip}.0/24 (Please wait 3s)...", "data": None})
        await async_ping_sweep(base_ip)
        
        await websocket.send_json({"status": "💻 Analyzing ARP routing tables...", "data": None})
        devices = get_arp_devices()
        
        def safe_sort(d):
            try:
                return int(d['ip'].split('.')[3])
            except:
                return 999
                
        devices.sort(key=safe_sort)
        devices.insert(0, {"ip": my_ip, "mac": "LOCAL HOST", "is_host": True})
        
        await websocket.send_json({"status": f"✅ Scan Complete. Detected {len(devices)} active devices.", "data": devices})
    except Exception as e:
        await websocket.send_json({"status": f"⚠️ Error: {str(e)}", "data": None})
    finally:
        await websocket.close()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888)