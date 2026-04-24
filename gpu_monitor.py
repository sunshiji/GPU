import asyncio
import subprocess
import json
import traceback
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


NVML_ERROR_CODES = {}
if NVML_AVAILABLE:
    try:
        for name in dir(pynvml):
            if name.startswith('NVML_ERROR_'):
                value = getattr(pynvml, name)
                NVML_ERROR_CODES[value] = name
    except:
        pass


def get_nvml_error_message(e: Exception) -> str:
    if hasattr(e, 'args') and len(e.args) > 0:
        err_code = e.args[0]
        if err_code in NVML_ERROR_CODES:
            return f"{NVML_ERROR_CODES[err_code]} ({err_code})"
        return f"Error code: {err_code}"
    return str(e)


@dataclass
class GPUProcess:
    pid: int
    process_name: str
    used_memory: int
    used_memory_mb: float
    has_permission: bool = True


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
    fan_speed_available: bool
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
            logger.warning("NVML not available - pynvml module not installed")
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
            logger.error(traceback.format_exc())
            self.initialized = False

    def get_gpu_count(self) -> int:
        return len(self.handles) if self.initialized else 0

    def _get_process_name(self, pid: int) -> str:
        try:
            import psutil
            process = psutil.Process(pid)
            return process.name()
        except psutil.NoSuchProcess:
            return "Process not found"
        except psutil.AccessDenied:
            return "Access denied"
        except Exception as e:
            logger.debug(f"Failed to get process name for PID {pid}: {e}")
            return "Unknown"

    def _get_fan_speed(self, handle, gpu_index: int) -> tuple:
        try:
            try:
                fan_count = pynvml.nvmlDeviceGetNumFans(handle)
                logger.debug(f"GPU {gpu_index}: Found {fan_count} fan(s)")
            except Exception as e:
                logger.debug(f"GPU {gpu_index}: nvmlDeviceGetNumFans failed - {get_nvml_error_message(e)}")
                fan_count = 1

            total_speed = 0
            valid_fans = 0
            
            for fan_idx in range(fan_count):
                try:
                    speed = pynvml.nvmlDeviceGetFanSpeed(handle, fan_idx)
                    logger.debug(f"GPU {gpu_index}: Fan {fan_idx} speed = {speed}%")
                    total_speed += speed
                    valid_fans += 1
                except pynvml.NVMLError as e:
                    err_msg = get_nvml_error_message(e)
                    if 'NOT_SUPPORTED' in err_msg or 'FUNCTION_NOT_FOUND' in err_msg:
                        logger.info(f"GPU {gpu_index}: Fan speed not supported for fan {fan_idx} - {err_msg}")
                    else:
                        logger.debug(f"GPU {gpu_index}: Failed to get fan {fan_idx} speed - {err_msg}")
                except Exception as e:
                    logger.debug(f"GPU {gpu_index}: Failed to get fan {fan_idx} speed - {e}")

            if valid_fans > 0:
                avg_speed = total_speed // valid_fans
                logger.debug(f"GPU {gpu_index}: Average fan speed = {avg_speed}% (from {valid_fans} fan(s))")
                return (avg_speed, True)
            else:
                logger.info(f"GPU {gpu_index}: No valid fan speed readings available")
                return (0, False)
                
        except Exception as e:
            logger.warning(f"GPU {gpu_index}: Failed to get fan speed via NVML: {e}")
            logger.debug(traceback.format_exc())
            return (0, False)

    def _get_processes(self, handle, gpu_index: int) -> List[GPUProcess]:
        processes = []
        seen_pids = set()

        try:
            logger.debug(f"GPU {gpu_index}: Getting compute processes...")
            compute_processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            logger.debug(f"GPU {gpu_index}: Found {len(compute_processes)} compute process(es)")
            
            for proc in compute_processes:
                pid = proc.pid
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                
                used_mem = proc.usedGpuMemory if hasattr(proc, 'usedGpuMemory') and proc.usedGpuMemory is not None else 0
                proc_name = self._get_process_name(pid)
                
                logger.debug(f"GPU {gpu_index}: Compute process PID={pid}, name={proc_name}, memory={used_mem}")
                
                processes.append(GPUProcess(
                    pid=pid,
                    process_name=proc_name,
                    used_memory=used_mem,
                    used_memory_mb=used_mem / 1024 / 1024 if used_mem > 0 else 0.0,
                    has_permission=True
                ))
        except pynvml.NVMLError as e:
            err_msg = get_nvml_error_message(e)
            if 'NOT_SUPPORTED' in err_msg or 'FUNCTION_NOT_FOUND' in err_msg:
                logger.info(f"GPU {gpu_index}: Compute processes not supported via NVML - {err_msg}")
            else:
                logger.warning(f"GPU {gpu_index}: Failed to get compute processes via NVML: {err_msg}")
        except Exception as e:
            logger.warning(f"GPU {gpu_index}: Failed to get compute processes via NVML: {e}")
            logger.debug(traceback.format_exc())

        try:
            logger.debug(f"GPU {gpu_index}: Getting graphics processes...")
            graphics_processes = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
            logger.debug(f"GPU {gpu_index}: Found {len(graphics_processes)} graphics process(es)")
            
            for proc in graphics_processes:
                pid = proc.pid
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                
                used_mem = proc.usedGpuMemory if hasattr(proc, 'usedGpuMemory') and proc.usedGpuMemory is not None else 0
                proc_name = self._get_process_name(pid)
                
                logger.debug(f"GPU {gpu_index}: Graphics process PID={pid}, name={proc_name}, memory={used_mem}")
                
                processes.append(GPUProcess(
                    pid=pid,
                    process_name=proc_name,
                    used_memory=used_mem,
                    used_memory_mb=used_mem / 1024 / 1024 if used_mem > 0 else 0.0,
                    has_permission=True
                ))
        except pynvml.NVMLError as e:
            err_msg = get_nvml_error_message(e)
            if 'NOT_SUPPORTED' in err_msg or 'FUNCTION_NOT_FOUND' in err_msg:
                logger.info(f"GPU {gpu_index}: Graphics processes not supported via NVML - {err_msg}")
            else:
                logger.warning(f"GPU {gpu_index}: Failed to get graphics processes via NVML: {err_msg}")
        except Exception as e:
            logger.warning(f"GPU {gpu_index}: Failed to get graphics processes via NVML: {e}")
            logger.debug(traceback.format_exc())

        logger.info(f"GPU {gpu_index}: NVML found {len(processes)} process(es) total")
        return processes

    def get_gpu_data(self, index: int) -> Optional[GPUData]:
        if not self.initialized or index >= len(self.handles):
            return None
        
        handle = self.handles[index]
        gpu_name = "Unknown"
        
        try:
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            gpu_name = name
            logger.debug(f"GPU {index}: Getting data for {name}")
            
            uuid = pynvml.nvmlDeviceGetUUID(handle)
            if isinstance(uuid, bytes):
                uuid = uuid.decode('utf-8')

            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                logger.debug(f"GPU {index}: Temperature = {temp}°C")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.warning(f"GPU {index}: Failed to get temperature: {err_msg}")
                temp = 0
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get temperature: {e}")
                temp = 0

            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                util_gpu = util.gpu
                util_mem = util.memory
                logger.debug(f"GPU {index}: GPU utilization = {util_gpu}%, Memory utilization = {util_mem}%")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.warning(f"GPU {index}: Failed to get utilization: {err_msg}")
                util_gpu = 0.0
                util_mem = 0.0
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get utilization: {e}")
                util_gpu = 0.0
                util_mem = 0.0

            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                mem_total = mem_info.total
                mem_used = mem_info.used
                mem_free = mem_info.free
                logger.debug(f"GPU {index}: Memory used = {mem_used / 1024 / 1024:.1f} MB / {mem_total / 1024 / 1024:.1f} MB")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.warning(f"GPU {index}: Failed to get memory info: {err_msg}")
                mem_total = 0
                mem_used = 0
                mem_free = 0
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get memory info: {e}")
                mem_total = 0
                mem_used = 0
                mem_free = 0

            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0.0

            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                logger.debug(f"GPU {index}: Power draw = {power:.1f} W")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.info(f"GPU {index}: Power usage not available: {err_msg}")
                power = 0.0
            except Exception as e:
                logger.info(f"GPU {index}: Power usage not available: {e}")
                power = 0.0

            try:
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
                logger.debug(f"GPU {index}: Power limit = {power_limit:.1f} W")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.info(f"GPU {index}: Power limit not available: {err_msg}")
                power_limit = 0.0
            except Exception as e:
                logger.info(f"GPU {index}: Power limit not available: {e}")
                power_limit = 0.0

            fan_speed, fan_available = self._get_fan_speed(handle, index)
            if not fan_available:
                logger.info(f"GPU {index}: Fan speed monitoring not available via NVML (common on laptop GPUs)")

            try:
                clock_gpu = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                logger.debug(f"GPU {index}: Graphics clock = {clock_gpu} MHz")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.warning(f"GPU {index}: Failed to get graphics clock: {err_msg}")
                clock_gpu = 0
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get graphics clock: {e}")
                clock_gpu = 0

            try:
                clock_mem = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                logger.debug(f"GPU {index}: Memory clock = {clock_mem} MHz")
            except pynvml.NVMLError as e:
                err_msg = get_nvml_error_message(e)
                logger.warning(f"GPU {index}: Failed to get memory clock: {err_msg}")
                clock_mem = 0
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get memory clock: {e}")
                clock_mem = 0

            try:
                driver_version = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver_version, bytes):
                    driver_version = driver_version.decode('utf-8')
                logger.debug(f"GPU {index}: Driver version = {driver_version}")
            except Exception as e:
                logger.warning(f"GPU {index}: Failed to get driver version: {e}")
                driver_version = "Unknown"

            processes = self._get_processes(handle, index)

            gpu_data = GPUData(
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
                fan_speed=fan_speed,
                fan_speed_available=fan_available,
                clock_gpu=clock_gpu,
                clock_memory=clock_mem,
                processes=processes,
                driver_version=driver_version
            )
            
            logger.info(f"GPU {index}: NVML data collected - temp={temp}°C, util={util_gpu}%, processes={len(processes)}")
            return gpu_data
            
        except Exception as e:
            logger.error(f"GPU {index}: Failed to get GPU data via NVML: {e}")
            logger.error(traceback.format_exc())
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
            except Exception as e:
                logger.warning(f"NVML shutdown error: {e}")
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
        except psutil.NoSuchProcess:
            return "Process not found"
        except psutil.AccessDenied:
            return "Access denied"
        except Exception as e:
            logger.debug(f"Failed to get process name for PID {pid}: {e}")
            return "Unknown"

    def _parse_memory_value(self, value: str) -> int:
        if not value or value == '[N/A]':
            return 0
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

    def _run_nvidia_smi(self, args: List[str], gpu_index: Optional[int] = None) -> Optional[str]:
        cmd = [self.nvidia_smi_path]
        if gpu_index is not None:
            cmd.append(f"--id={gpu_index}")
        cmd.extend(args)
        
        logger.debug(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                logger.warning(f"nvidia-smi command failed with return code {result.returncode}")
                if result.stderr:
                    logger.warning(f"nvidia-smi stderr: {result.stderr.strip()}")
                return None
            
            logger.debug(f"nvidia-smi stdout: {result.stdout.strip()}")
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("nvidia-smi command timed out")
            return None
        except Exception as e:
            logger.error(f"nvidia-smi command failed: {e}")
            logger.debug(traceback.format_exc())
            return None

    def _get_processes_from_smi(self, gpu_index: int) -> List[GPUProcess]:
        processes = []
        seen_pids = set()

        query_fields = ["pid", "used_gpu_memory", "process_name"]
        
        logger.debug(f"GPU {gpu_index}: Querying compute apps with nvidia-smi...")
        
        output = self._run_nvidia_smi(
            [
                f"--query-compute-apps={','.join(query_fields)}",
                "--format=csv"
            ],
            gpu_index
        )
        
        if output:
            lines = output.strip().split('\n')
            if len(lines) > 0:
                header = lines[0]
                logger.debug(f"GPU {gpu_index}: Compute apps header: {header}")
                
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    
                    parts = [p.strip() for p in line.split(',', 2)]
                    
                    if len(parts) >= 1 and parts[0].isdigit():
                        pid = int(parts[0])
                        if pid in seen_pids:
                            continue
                        seen_pids.add(pid)
                        
                        used_mem_str = parts[1] if len(parts) > 1 else '[N/A]'
                        process_name = parts[2] if len(parts) > 2 else ''
                        
                        has_permission = True
                        if 'Insufficient Permissions' in process_name or 'Insufficient' in process_name:
                            has_permission = False
                            logger.debug(f"GPU {gpu_index}: Process PID={pid} has insufficient permissions")
                        
                        if not process_name or 'Insufficient' in process_name:
                            process_name = self._get_process_name(pid)
                        
                        used_mem = self._parse_memory_value(used_mem_str)
                        
                        logger.debug(f"GPU {gpu_index}: Compute app PID={pid}, name={process_name}, memory={used_mem_str}, permission={has_permission}")
                        
                        processes.append(GPUProcess(
                            pid=pid,
                            process_name=process_name,
                            used_memory=used_mem,
                            used_memory_mb=used_mem / 1024 / 1024 if used_mem > 0 else 0.0,
                            has_permission=has_permission
                        ))

        logger.info(f"GPU {gpu_index}: nvidia-smi found {len(processes)} process(es)")
        
        if len(processes) == 0:
            logger.info(f"GPU {gpu_index}: Note: On Windows, process memory info may require admin privileges")
            logger.info(f"GPU {gpu_index}: Try running as Administrator for full process visibility")
        
        return processes

    def get_gpu_data(self, index: int) -> Optional[GPUData]:
        if not self.is_available():
            return None
        
        logger.debug(f"GPU {index}: Getting data via nvidia-smi...")
        
        query_fields = [
            "index", "name", "uuid", "temperature.gpu",
            "utilization.gpu", "utilization.memory",
            "memory.total", "memory.used", "memory.free",
            "power.draw", "power.limit", "fan.speed",
            "clocks.current.graphics", "clocks.current.memory",
            "driver_version"
        ]
        
        output = self._run_nvidia_smi(
            [
                f"--query-gpu={','.join(query_fields)}",
                "--format=csv,noheader,nounits"
            ],
            index
        )
        
        if not output:
            return None

        values = [v.strip() for v in output.strip().split(',')]
        if len(values) < len(query_fields):
            logger.warning(f"GPU {index}: Expected {len(query_fields)} values, got {len(values)}")
            return None

        logger.debug(f"GPU {index}: nvidia-smi values: {values}")

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
        
        fan_speed_available = True
        if values[11] == '[N/A]':
            fan_speed = 0
            fan_speed_available = False
            logger.info(f"GPU {index}: Fan speed reports [N/A] via nvidia-smi (common on laptop GPUs)")
        else:
            fan_speed = int(float(values[11])) if values[11] else 0
        
        clock_gpu = int(float(values[12])) if values[12] and values[12] != '[N/A]' else 0
        clock_mem = int(float(values[13])) if values[13] and values[13] != '[N/A]' else 0
        
        driver_version = values[14] if len(values) > 14 else "Unknown"

        processes = self._get_processes_from_smi(index)

        gpu_data = GPUData(
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
            fan_speed=fan_speed,
            fan_speed_available=fan_speed_available,
            clock_gpu=clock_gpu,
            clock_memory=clock_mem,
            processes=processes,
            driver_version=driver_version
        )
        
        logger.info(f"GPU {index}: nvidia-smi data collected - temp={temp}°C, util={util_gpu}%, fan_available={fan_speed_available}, processes={len(processes)}")
        return gpu_data

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
        
        logger.info("=" * 60)
        logger.info("GPU Monitor Initialization Summary")
        logger.info("=" * 60)
        logger.info(f"NVML Available: {NVML_AVAILABLE}")
        logger.info(f"NVML Initialized: {self.nvml_monitor.initialized}")
        logger.info(f"nvidia-smi Available: {self.smi_monitor.is_available()}")
        logger.info(f"Active Monitor: {'NVML' if self.use_nvml else 'nvidia-smi' if self.smi_monitor.is_available() else 'None'}")
        logger.info(f"GPU Count: {self.get_gpu_count()}")
        logger.info("=" * 60)
        
        if not self.use_nvml and not self.smi_monitor.is_available():
            logger.warning("Neither NVML nor nvidia-smi is available - GPU monitoring will not work")

    def get_gpu_count(self) -> int:
        if self.use_nvml:
            return self.nvml_monitor.get_gpu_count()
        elif self.smi_monitor.is_available():
            return self.smi_monitor.get_gpu_count()
        return 0

    def get_all_gpus(self) -> List[Dict[str, Any]]:
        gpus = []
        
        if self.use_nvml:
            logger.debug("Using NVML for GPU data collection")
            gpu_data_list = self.nvml_monitor.get_all_gpus()
            
            if not gpu_data_list or len(gpu_data_list) == 0:
                logger.warning("NVML returned no data, trying nvidia-smi as fallback")
                if self.smi_monitor.is_available():
                    gpu_data_list = self.smi_monitor.get_all_gpus()
            else:
                if self.smi_monitor.is_available():
                    logger.debug("Checking if we need to supplement process data from nvidia-smi")
                    for i, gpu in enumerate(gpu_data_list):
                        if len(gpu.processes) == 0:
                            logger.info(f"GPU {gpu.index}: No processes from NVML, trying nvidia-smi...")
                            try:
                                smi_data = self.smi_monitor.get_gpu_data(gpu.index)
                                if smi_data and len(smi_data.processes) > 0:
                                    logger.info(f"GPU {gpu.index}: Found {len(smi_data.processes)} process(es) from nvidia-smi")
                                    gpu_data_list[i].processes = smi_data.processes
                            except Exception as e:
                                logger.warning(f"GPU {gpu.index}: Failed to get process data from nvidia-smi: {e}")
        elif self.smi_monitor.is_available():
            logger.debug("Using nvidia-smi for GPU data collection")
            gpu_data_list = self.smi_monitor.get_all_gpus()
        else:
            logger.error("No GPU monitoring method available")
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
