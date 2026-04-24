import asyncio
import subprocess
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import logging

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class GPUProcess:
    pid: int
    process_name: str
    used_memory: int
    used_memory_mb: float


@dataclass
class GPUData:
    index: int
    name: str
    uuid: str
    temperature: int
    temperature_max: int
    utilization_gpu: float
    utilization_memory: float
    memory_total: int
    memory_used: int
    memory_free: int
    memory_used_percent: float
    power_draw: float
    power_limit: float
    fan_speed: int
    clock_gpu: int
    clock_memory: int
    processes: List[GPUProcess]
    driver_version: str


class NVMLMonitor:
    def __init__(self):
        self.initialized = False
        self.handles: List[Any] = []
        self._init_nvml()

    def _init_nvml(self):
        if not NVML_AVAILABLE:
            logger.warning("NVML not available")
            return
        try:
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                self.handles.append(handle)
            self.initialized = True
            logger.info(f"NVML initialized, found {device_count} GPU(s)")
        except Exception as e:
            logger.error(f"NVML initialization failed: {e}")
            self.initialized = False

    def get_gpu_count(self) -> int:
        return len(self.handles) if self.initialized else 0

    def _get_process_name(self, pid: int) -> str:
        try:
            import psutil
            process = psutil.Process(pid)
            return process.name()
        except:
            return "Unknown"

    def get_gpu_data(self, index: int) -> Optional[GPUData]:
        if not self.initialized or index >= len(self.handles):
            return None
        
        handle = self.handles[index]
        try:
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            
            uuid = pynvml.nvmlDeviceGetUUID(handle)
            if isinstance(uuid, bytes):
                uuid = uuid.decode('utf-8')

            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except:
                temp = 0

            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                util_gpu = util.gpu
                util_mem = util.memory
            except:
                util_gpu = 0.0
                util_mem = 0.0

            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_total = mem_info.total
                mem_used = mem_info.used
                mem_free = mem_info.free
            except:
                mem_total = 0
                mem_used = 0
                mem_free = 0

            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0.0

            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except:
                power = 0.0

            try:
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
            except:
                power_limit = 0.0

            try:
                fan = pynvml.nvmlDeviceGetFanSpeed(handle)
            except:
                fan = 0

            try:
                clock_gpu = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
            except:
                clock_gpu = 0

            try:
                clock_mem = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
            except:
                clock_mem = 0

            try:
                driver_version = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver_version, bytes):
                    driver_version = driver_version.decode('utf-8')
            except:
                driver_version = "Unknown"

            processes = []
            try:
                compute_processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                for proc in compute_processes:
                    used_mem = proc.usedGpuMemory if hasattr(proc, 'usedGpuMemory') else 0
                    processes.append(GPUProcess(
                        pid=proc.pid,
                        process_name=self._get_process_name(proc.pid),
                        used_memory=used_mem,
                        used_memory_mb=used_mem / 1024 / 1024
                    ))
            except:
                pass

            try:
                graphics_processes = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
                existing_pids = {p.pid for p in processes}
                for proc in graphics_processes:
                    if proc.pid not in existing_pids:
                        used_mem = proc.usedGpuMemory if hasattr(proc, 'usedGpuMemory') else 0
                        processes.append(GPUProcess(
                            pid=proc.pid,
                            process_name=self._get_process_name(proc.pid),
                            used_memory=used_mem,
                            used_memory_mb=used_mem / 1024 / 1024
                        ))
            except:
                pass

            return GPUData(
                index=index,
                name=name,
                uuid=uuid,
                temperature=temp,
                temperature_max=120,
                utilization_gpu=util_gpu,
                utilization_memory=util_mem,
                memory_total=mem_total,
                memory_used=mem_used,
                memory_free=mem_free,
                memory_used_percent=mem_percent,
                power_draw=power,
                power_limit=power_limit,
                fan_speed=fan,
                clock_gpu=clock_gpu,
                clock_memory=clock_mem,
                processes=processes,
                driver_version=driver_version
            )
        except Exception as e:
            logger.error(f"Failed to get GPU data for index {index}: {e}")
            return None

    def get_all_gpus(self) -> List[GPUData]:
        gpus = []
        for i in range(self.get_gpu_count()):
            data = self.get_gpu_data(i)
            if data:
                gpus.append(data)
        return gpus

    def shutdown(self):
        if self.initialized:
            try:
                pynvml.nvmlShutdown()
                logger.info("NVML shutdown")
            except:
                pass
            self.initialized = False


class NvidiaSmiMonitor:
    def __init__(self):
        self.nvidia_smi_path = self._find_nvidia_smi()

    def _find_nvidia_smi(self) -> Optional[str]:
        possible_paths = [
            "nvidia-smi",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            r"C:\Windows\System32\nvidia-smi.exe",
        ]
        for path in possible_paths:
            try:
                result = subprocess.run(
                    [path, "--help"],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logger.info(f"Found nvidia-smi at: {path}")
                    return path
            except:
                continue
        logger.warning("nvidia-smi not found")
        return None

    def is_available(self) -> bool:
        return self.nvidia_smi_path is not None

    def _get_process_name(self, pid: int) -> str:
        try:
            import psutil
            process = psutil.Process(pid)
            return process.name()
        except:
            return "Unknown"

    def _parse_memory_value(self, value: str) -> int:
        value = value.strip().upper()
        if 'MIB' in value:
            return int(float(value.replace('MIB', '').strip())) * 1024 * 1024
        elif 'GIB' in value:
            return int(float(value.replace('GIB', '').strip())) * 1024 * 1024 * 1024
        elif 'MB' in value:
            return int(float(value.replace('MB', '').strip())) * 1024 * 1024
        elif 'GB' in value:
            return int(float(value.replace('GB', '').strip())) * 1024 * 1024 * 1024
        try:
            return int(float(value))
        except:
            return 0

    def get_gpu_count(self) -> int:
        if not self.is_available():
            return 0
        try:
            result = subprocess.run(
                [self.nvidia_smi_path, "--query-gpu=count", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except:
            pass
        return 0

    def get_gpu_data(self, index: int) -> Optional[GPUData]:
        if not self.is_available():
            return None
        
        try:
            query_fields = [
                "index", "name", "uuid", "temperature.gpu",
                "utilization.gpu", "utilization.memory",
                "memory.total", "memory.used", "memory.free",
                "power.draw", "power.limit", "fan.speed",
                "clocks.current.graphics", "clocks.current.memory",
                "driver_version"
            ]
            
            result = subprocess.run(
                [
                    self.nvidia_smi_path,
                    f"--id={index}",
                    f"--query-gpu={','.join(query_fields)}",
                    "--format=csv,noheader,nounits"
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return None

            values = [v.strip() for v in result.stdout.strip().split(',')]
            if len(values) < len(query_fields):
                return None

            idx = int(values[0]) if values[0].isdigit() else index
            name = values[1]
            uuid = values[2]
            
            temp = int(float(values[3])) if values[3] and values[3] != '[N/A]' else 0
            
            util_gpu = float(values[4].strip('%')) if values[4] and values[4] != '[N/A]' else 0.0
            util_mem = float(values[5].strip('%')) if values[5] and values[5] != '[N/A]' else 0.0
            
            mem_total = self._parse_memory_value(values[6])
            mem_used = self._parse_memory_value(values[7])
            mem_free = self._parse_memory_value(values[8])
            
            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0.0
            
            power = float(values[9]) if values[9] and values[9] != '[N/A]' else 0.0
            power_limit = float(values[10]) if values[10] and values[10] != '[N/A]' else 0.0
            
            fan = int(float(values[11])) if values[11] and values[11] != '[N/A]' else 0
            
            clock_gpu = int(float(values[12])) if values[12] and values[12] != '[N/A]' else 0
            clock_mem = int(float(values[13])) if values[13] and values[13] != '[N/A]' else 0
            
            driver_version = values[14] if len(values) > 14 else "Unknown"

            processes = []
            try:
                proc_result = subprocess.run(
                    [
                        self.nvidia_smi_path,
                        f"--id={index}",
                        "--query-compute-apps=pid,used_gpu_memory",
                        "--format=csv,noheader,nounits"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if proc_result.returncode == 0:
                    for line in proc_result.stdout.strip().split('\n'):
                        if not line or '[N/A]' in line:
                            continue
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) >= 2 and parts[0].isdigit():
                            pid = int(parts[0])
                            used_mem = self._parse_memory_value(parts[1])
                            processes.append(GPUProcess(
                                pid=pid,
                                process_name=self._get_process_name(pid),
                                used_memory=used_mem,
                                used_memory_mb=used_mem / 1024 / 1024
                            ))
            except:
                pass

            return GPUData(
                index=idx,
                name=name,
                uuid=uuid,
                temperature=temp,
                temperature_max=120,
                utilization_gpu=util_gpu,
                utilization_memory=util_mem,
                memory_total=mem_total,
                memory_used=mem_used,
                memory_free=mem_free,
                memory_used_percent=mem_percent,
                power_draw=power,
                power_limit=power_limit,
                fan_speed=fan,
                clock_gpu=clock_gpu,
                clock_memory=clock_mem,
                processes=processes,
                driver_version=driver_version
            )
        except Exception as e:
            logger.error(f"Failed to get GPU data via nvidia-smi for index {index}: {e}")
            return None

    def get_all_gpus(self) -> List[GPUData]:
        gpus = []
        count = self.get_gpu_count()
        for i in range(count):
            data = self.get_gpu_data(i)
            if data:
                gpus.append(data)
        return gpus


class GPUMonitor:
    def __init__(self):
        self.nvml_monitor = NVMLMonitor()
        self.smi_monitor = NvidiaSmiMonitor()
        self.use_nvml = self.nvml_monitor.initialized
        if not self.use_nvml and not self.smi_monitor.is_available():
            logger.warning("Neither NVML nor nvidia-smi is available")

    def get_gpu_count(self) -> int:
        if self.use_nvml:
            return self.nvml_monitor.get_gpu_count()
        elif self.smi_monitor.is_available():
            return self.smi_monitor.get_gpu_count()
        return 0

    def get_all_gpus(self) -> List[Dict[str, Any]]:
        gpus = []
        if self.use_nvml:
            gpu_data_list = self.nvml_monitor.get_all_gpus()
        elif self.smi_monitor.is_available():
            gpu_data_list = self.smi_monitor.get_all_gpus()
        else:
            return []

        for gpu in gpu_data_list:
            gpu_dict = asdict(gpu)
            gpu_dict['memory_total_mb'] = gpu.memory_total / 1024 / 1024
            gpu_dict['memory_used_mb'] = gpu.memory_used / 1024 / 1024
            gpu_dict['memory_free_mb'] = gpu.memory_free / 1024 / 1024
            gpu_dict['data_source'] = 'NVML' if self.use_nvml else 'nvidia-smi'
            gpus.append(gpu_dict)
        
        return gpus

    def get_monitor_info(self) -> Dict[str, Any]:
        return {
            'nvml_available': NVML_AVAILABLE,
            'nvml_initialized': self.nvml_monitor.initialized,
            'nvidia_smi_available': self.smi_monitor.is_available(),
            'active_monitor': 'NVML' if self.use_nvml else 'nvidia-smi' if self.smi_monitor.is_available() else 'None',
            'gpu_count': self.get_gpu_count()
        }

    def shutdown(self):
        self.nvml_monitor.shutdown()


gpu_monitor = GPUMonitor()
