import psutil
import platform
import socket
from typing import Dict, Any, List
from dataclasses import dataclass, asdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CPUInfo:
    count: int
    count_physical: int
    percent: float
    per_cpu_percent: List[float]
    frequency_current: float
    frequency_min: float
    frequency_max: float
    load_avg_1: float
    load_avg_5: float
    load_avg_15: float


@dataclass
class MemoryInfo:
    total: int
    available: int
    used: int
    percent: float
    total_mb: float
    available_mb: float
    used_mb: float


@dataclass
class SwapInfo:
    total: int
    used: int
    free: int
    percent: float
    total_mb: float
    used_mb: float
    free_mb: float


@dataclass
class DiskPartition:
    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float
    total_gb: float
    used_gb: float
    free_gb: float


@dataclass
class NetworkInterface:
    name: str
    is_up: bool
    duplex: str
    speed: int
    mtu: int
    ipv4: str
    ipv6: str
    mac: str


@dataclass
class NetworkStats:
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errin: int
    errout: int
    dropin: int
    dropout: int
    bytes_sent_mb: float
    bytes_recv_mb: float


@dataclass
class SystemInfo:
    hostname: str
    os: str
    os_version: str
    architecture: str
    cpu_brand: str
    boot_time: float
    uptime_seconds: float
    uptime_hours: float


class SystemMonitor:
    def __init__(self):
        self._last_net_io = None
        self._last_net_time = None

    def get_cpu_info(self) -> CPUInfo:
        try:
            count = psutil.cpu_count() or 0
            count_physical = psutil.cpu_count(logical=False) or count
            
            percent = psutil.cpu_percent(interval=0.1)
            per_cpu_percent = psutil.cpu_percent(interval=0, percpu=True)
            
            freq = psutil.cpu_freq()
            if freq:
                freq_current = freq.current
                freq_min = freq.min
                freq_max = freq.max
            else:
                freq_current = freq_min = freq_max = 0.0

            try:
                load1, load5, load15 = psutil.getloadavg()
            except (AttributeError, OSError):
                load1 = load5 = load15 = 0.0

            return CPUInfo(
                count=count,
                count_physical=count_physical,
                percent=percent,
                per_cpu_percent=per_cpu_percent,
                frequency_current=freq_current,
                frequency_min=freq_min,
                frequency_max=freq_max,
                load_avg_1=load1,
                load_avg_5=load5,
                load_avg_15=load15
            )
        except Exception as e:
            logger.error(f"Failed to get CPU info: {e}")
            return CPUInfo(
                count=0, count_physical=0, percent=0.0, per_cpu_percent=[],
                frequency_current=0.0, frequency_min=0.0, frequency_max=0.0,
                load_avg_1=0.0, load_avg_5=0.0, load_avg_15=0.0
            )

    def get_memory_info(self) -> MemoryInfo:
        try:
            mem = psutil.virtual_memory()
            return MemoryInfo(
                total=mem.total,
                available=mem.available,
                used=mem.used,
                percent=mem.percent,
                total_mb=mem.total / 1024 / 1024,
                available_mb=mem.available / 1024 / 1024,
                used_mb=mem.used / 1024 / 1024
            )
        except Exception as e:
            logger.error(f"Failed to get memory info: {e}")
            return MemoryInfo(
                total=0, available=0, used=0, percent=0.0,
                total_mb=0.0, available_mb=0.0, used_mb=0.0
            )

    def get_swap_info(self) -> SwapInfo:
        try:
            swap = psutil.swap_memory()
            return SwapInfo(
                total=swap.total,
                used=swap.used,
                free=swap.free,
                percent=swap.percent,
                total_mb=swap.total / 1024 / 1024,
                used_mb=swap.used / 1024 / 1024,
                free_mb=swap.free / 1024 / 1024
            )
        except Exception as e:
            logger.error(f"Failed to get swap info: {e}")
            return SwapInfo(
                total=0, used=0, free=0, percent=0.0,
                total_mb=0.0, used_mb=0.0, free_mb=0.0
            )

    def get_disk_partitions(self) -> List[DiskPartition]:
        partitions = []
        try:
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    partitions.append(DiskPartition(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        fstype=part.fstype,
                        total=usage.total,
                        used=usage.used,
                        free=usage.free,
                        percent=usage.percent,
                        total_gb=usage.total / 1024 / 1024 / 1024,
                        used_gb=usage.used / 1024 / 1024 / 1024,
                        free_gb=usage.free / 1024 / 1024 / 1024
                    ))
                except (PermissionError, OSError):
                    continue
        except Exception as e:
            logger.error(f"Failed to get disk partitions: {e}")
        return partitions

    def get_network_interfaces(self) -> List[NetworkInterface]:
        interfaces = []
        try:
            if_addrs = psutil.net_if_addrs()
            if_stats = psutil.net_if_stats()

            for name, addrs in if_addrs.items():
                stats = if_stats.get(name)
                if not stats:
                    continue

                ipv4 = ""
                ipv6 = ""
                mac = ""

                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ipv4 = addr.address
                    elif addr.family == socket.AF_INET6:
                        ipv6 = addr.address.split('%')[0]
                    elif addr.family == psutil.AF_LINK if hasattr(psutil, 'AF_LINK') else -1:
                        mac = addr.address

                duplex_map = {
                    psutil.NIC_DUPLEX_FULL: "full",
                    psutil.NIC_DUPLEX_HALF: "half",
                    psutil.NIC_DUPLEX_UNKNOWN: "unknown"
                }

                interfaces.append(NetworkInterface(
                    name=name,
                    is_up=stats.isup,
                    duplex=duplex_map.get(stats.duplex, "unknown"),
                    speed=stats.speed,
                    mtu=stats.mtu,
                    ipv4=ipv4,
                    ipv6=ipv6,
                    mac=mac
                ))
        except Exception as e:
            logger.error(f"Failed to get network interfaces: {e}")
        return interfaces

    def get_network_stats(self) -> NetworkStats:
        try:
            net_io = psutil.net_io_counters()
            return NetworkStats(
                bytes_sent=net_io.bytes_sent,
                bytes_recv=net_io.bytes_recv,
                packets_sent=net_io.packets_sent,
                packets_recv=net_io.packets_recv,
                errin=net_io.errin,
                errout=net_io.errout,
                dropin=net_io.dropin,
                dropout=net_io.dropout,
                bytes_sent_mb=net_io.bytes_sent / 1024 / 1024,
                bytes_recv_mb=net_io.bytes_recv / 1024 / 1024
            )
        except Exception as e:
            logger.error(f"Failed to get network stats: {e}")
            return NetworkStats(
                bytes_sent=0, bytes_recv=0, packets_sent=0, packets_recv=0,
                errin=0, errout=0, dropin=0, dropout=0,
                bytes_sent_mb=0.0, bytes_recv_mb=0.0
            )

    def get_system_info(self) -> SystemInfo:
        try:
            import time
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time

            cpu_brand = ""
            try:
                if platform.system() == "Windows":
                    import winreg
                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                    )
                    cpu_brand, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    winreg.CloseKey(key)
                else:
                    with open("/proc/cpuinfo", "r") as f:
                        for line in f:
                            if line.startswith("model name"):
                                cpu_brand = line.split(":")[1].strip()
                                break
            except:
                cpu_brand = platform.processor() or "Unknown"

            return SystemInfo(
                hostname=platform.node(),
                os=platform.system(),
                os_version=platform.version(),
                architecture=platform.machine(),
                cpu_brand=cpu_brand.strip(),
                boot_time=boot_time,
                uptime_seconds=uptime,
                uptime_hours=uptime / 3600
            )
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return SystemInfo(
                hostname="Unknown", os="Unknown", os_version="Unknown",
                architecture="Unknown", cpu_brand="Unknown",
                boot_time=0.0, uptime_seconds=0.0, uptime_hours=0.0
            )

    def get_all_stats(self) -> Dict[str, Any]:
        return {
            'cpu': asdict(self.get_cpu_info()),
            'memory': asdict(self.get_memory_info()),
            'swap': asdict(self.get_swap_info()),
            'disks': [asdict(p) for p in self.get_disk_partitions()],
            'network_interfaces': [asdict(i) for i in self.get_network_interfaces()],
            'network_stats': asdict(self.get_network_stats()),
            'system': asdict(self.get_system_info())
        }


system_monitor = SystemMonitor()
