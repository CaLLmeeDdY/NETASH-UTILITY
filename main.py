from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import speedtest
import asyncio
import uvicorn
import subprocess
import re

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

# --- SPEEDTEST MODULE (Untouched) ---
def get_speedtest_results():
    st = speedtest.Speedtest(secure=True)
    st.get_best_server()
    return {
        "ping": round(st.results.ping, 1), 
        "download": round(st.download() / 1_000_000, 2), 
        "upload": round(st.upload() / 1_000_000, 2), 
        "isp": st.results.client.get('isp', 'Unknown ISP')
    }

@app.websocket("/ws/speedtest")
async def ws_speedtest(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        await websocket.send_json({"status": "🔗 Connected. Identifying ISP...", "data": None})
        results = await loop.run_in_executor(None, get_speedtest_results)
        await websocket.send_json({"status": "✅ Test Success", "data": results})
    except Exception as e:
        await websocket.send_json({"status": f"⚠️ Error: {str(e)}", "data": None})
    finally:
        await websocket.close()

# --- NEW: PING PULSE MODULE ---
def ping_host(host):
    """Runs the Linux ping command and extracts the latency in ms."""
    try:
        # Ping exactly 1 time (-c 1) with a 1-second timeout (-W 1)
        output = subprocess.check_output(["ping", "-c", "1", "-W", "1", host], universal_newlines=True)
        # Search the text for 'time=XX.X ms'
        match = re.search(r'time=([\d.]+) ms', output)
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None # Returns None if the ping fails/times out

@app.websocket("/ws/ping")
async def ws_ping(websocket: WebSocket):
    await websocket.accept()
    try:
        # Wait for the frontend to tell us WHICH ip to ping
        target_ip = await websocket.receive_text() 
        
        # Loop endlessly until the user stops it
        while True:
            latency = ping_host(target_ip)
            if latency is not None:
                await websocket.send_json({"status": "success", "ping": latency})
            else:
                await websocket.send_json({"status": "timeout", "ping": 0})
            
            await asyncio.sleep(1) # Wait 1 second between pings
            
    except WebSocketDisconnect:
        print("Ping module disconnected.")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888)