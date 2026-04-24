import asyncio
import json
from datetime import datetime
from typing import Dict, Any, List, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

import config
from gpu_monitor import gpu_monitor
from system_monitor import system_monitor


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        if not self.active_connections:
            return
        json_message = json.dumps(message, default=str)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json_message)
            except:
                self.active_connections.discard(connection)


manager = ConnectionManager()


class DataStore:
    def __init__(self):
        self.gpu_history: Dict[int, Dict[str, List[Any]]] = {}
        self.system_history: Dict[str, List[Any]] = {}
        self.max_history_size = config.HISTORY_SIZE

    def _get_timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _ensure_gpu_history(self, gpu_index: int):
        if gpu_index not in self.gpu_history:
            self.gpu_history[gpu_index] = {
                'timestamp': [],
                'temperature': [],
                'utilization_gpu': [],
                'utilization_memory': [],
                'memory_used_percent': [],
                'power_draw': [],
                'fan_speed': [],
                'clock_gpu': [],
                'clock_memory': []
            }

    def _ensure_system_history(self):
        if not self.system_history:
            self.system_history = {
                'timestamp': [],
                'cpu_percent': [],
                'memory_percent': []
            }

    def _trim_history(self, history: Dict[str, List[Any]]):
        for key in history:
            if len(history[key]) > self.max_history_size:
                history[key] = history[key][-self.max_history_size:]

    def update_gpu_history(self, gpu_data_list: List[Dict[str, Any]]):
        timestamp = self._get_timestamp()
        for gpu in gpu_data_list:
            idx = gpu['index']
            self._ensure_gpu_history(idx)
            history = self.gpu_history[idx]
            
            history['timestamp'].append(timestamp)
            history['temperature'].append(gpu['temperature'])
            history['utilization_gpu'].append(gpu['utilization_gpu'])
            history['utilization_memory'].append(gpu['utilization_memory'])
            history['memory_used_percent'].append(gpu['memory_used_percent'])
            history['power_draw'].append(gpu['power_draw'])
            history['fan_speed'].append(gpu['fan_speed'])
            history['clock_gpu'].append(gpu['clock_gpu'])
            history['clock_memory'].append(gpu['clock_memory'])
            
            self._trim_history(history)

    def update_system_history(self, system_data: Dict[str, Any]):
        timestamp = self._get_timestamp()
        self._ensure_system_history()
        
        self.system_history['timestamp'].append(timestamp)
        self.system_history['cpu_percent'].append(system_data['cpu']['percent'])
        self.system_history['memory_percent'].append(system_data['memory']['percent'])
        
        self._trim_history(self.system_history)

    def get_gpu_history(self, gpu_index: int) -> Dict[str, List[Any]]:
        return self.gpu_history.get(gpu_index, {})

    def get_all_gpu_history(self) -> Dict[int, Dict[str, List[Any]]]:
        return self.gpu_history

    def get_system_history(self) -> Dict[str, List[Any]]:
        return self.system_history


data_store = DataStore()


async def data_collector():
    while True:
        try:
            gpu_data = gpu_monitor.get_all_gpus()
            system_data = system_monitor.get_all_stats()
            
            data_store.update_gpu_history(gpu_data)
            data_store.update_system_history(system_data)
            
            message = {
                'type': 'realtime',
                'timestamp': datetime.now().isoformat(),
                'gpus': gpu_data,
                'system': system_data,
                'gpu_history': data_store.get_all_gpu_history(),
                'system_history': data_store.get_system_history()
            }
            
            await manager.broadcast(message)
        except Exception as e:
            import logging
            logging.error(f"Data collector error: {e}")
        
        await asyncio.sleep(config.UPDATE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    collect_task = asyncio.create_task(data_collector())
    yield
    collect_task.cancel()
    try:
        await collect_task
    except asyncio.CancelledError:
        pass
    gpu_monitor.shutdown()


app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    import os
    template_path = os.path.join("templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    
    html = html.replace("{{ app_name }}", config.APP_NAME)
    html = html.replace("{{ version }}", config.VERSION)
    
    return HTMLResponse(content=html)


@app.get("/api/version")
async def get_version():
    return JSONResponse(content={
        "name": config.APP_NAME,
        "version": config.VERSION,
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/gpu-data")
async def get_gpu_data():
    gpu_data = gpu_monitor.get_all_gpus()
    monitor_info = gpu_monitor.get_monitor_info()
    
    return JSONResponse(content={
        "timestamp": datetime.now().isoformat(),
        "gpus": gpu_data,
        "monitor_info": monitor_info
    })


@app.get("/api/system-data")
async def get_system_data():
    system_data = system_monitor.get_all_stats()
    
    return JSONResponse(content={
        "timestamp": datetime.now().isoformat(),
        "system": system_data
    })


@app.get("/api/history")
async def get_history():
    return JSONResponse(content={
        "timestamp": datetime.now().isoformat(),
        "gpu_history": data_store.get_all_gpu_history(),
        "system_history": data_store.get_system_history()
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        initial_gpu_data = gpu_monitor.get_all_gpus()
        initial_system_data = system_monitor.get_all_stats()
        
        initial_message = {
            'type': 'initial',
            'timestamp': datetime.now().isoformat(),
            'gpus': initial_gpu_data,
            'system': initial_system_data,
            'gpu_history': data_store.get_all_gpu_history(),
            'system_history': data_store.get_system_history(),
            'monitor_info': gpu_monitor.get_monitor_info()
        }
        
        await websocket.send_text(json.dumps(initial_message, default=str))
        
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get('type') == 'ping':
                    await websocket.send_text(json.dumps({'type': 'pong', 'timestamp': datetime.now().isoformat()}))
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        import logging
        logging.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True
    )
