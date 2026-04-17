from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import speedtest
import asyncio
import uvicorn

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

def get_speedtest_results():
    """Attempts to run the actual test."""
    st = speedtest.Speedtest(secure=True)
    st.get_best_server()
    ping = st.results.ping
    dl = st.download() / 1_000_000
    ul = st.upload() / 1_000_000
    isp = st.results.client.get('isp', 'Unknown ISP')
    return {"ping": round(ping, 1), "download": round(dl, 2), "upload": round(ul, 2), "isp": isp}

@app.websocket("/ws/speedtest")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        await websocket.send_json({"status": "🔗 WebSocket Connected", "data": None})
        await asyncio.sleep(1) # Small pause for UI
        
        await websocket.send_json({"status": "🔍 Identifying ISP & Server...", "data": None})
        
        # Run the heavy speedtest logic in a separate thread
        try:
            results = await loop.run_in_executor(None, get_speedtest_results)
            await websocket.send_json({"status": "✅ Test Success", "data": results})
        except Exception as e:
            await websocket.send_json({"status": f"⚠️ Speedtest Lib Error: {str(e)}", "data": None})
            # Fallback to prove connection is still alive
            await websocket.send_json({"status": "ℹ️ Connection is OK, but Speedtest library failed.", "data": {"ping": 0, "download": 0, "upload": 0}})

    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8888)