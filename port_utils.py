import socket
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


def is_port_in_use(host: str, port: int) -> bool:
    """
    检查指定端口是否被占用
    
    Args:
        host: 主机地址
        port: 端口号
    
    Returns:
        True 如果端口被占用，False 如果端口可用
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            result = s.bind((host, port))
            return False
    except socket.error as e:
        if e.errno in [48, 98, 10048]:
            logger.debug(f"Port {port} is already in use (errno: {e.errno})")
            return True
        else:
            logger.error(f"Error checking port {port}: {e}")
            return True
    except Exception as e:
        logger.error(f"Unexpected error checking port {port}: {e}")
        return True


def find_available_port(
    host: str,
    start_port: int,
    end_port: int,
    preferred_port: Optional[int] = None
) -> Tuple[int, bool]:
    """
    在指定范围内查找可用端口
    
    Args:
        host: 主机地址
        start_port: 起始端口
        end_port: 结束端口
        preferred_port: 首选端口
    
    Returns:
        (可用端口号, 是否使用了首选端口)
    """
    if preferred_port is not None:
        if not is_port_in_use(host, preferred_port):
            logger.info(f"Preferred port {preferred_port} is available")
            return (preferred_port, True)
        else:
            logger.warning(f"Preferred port {preferred_port} is in use")
    
    logger.info(f"Searching for available port in range {start_port}-{end_port}...")
    
    for port in range(start_port, end_port + 1):
        if not is_port_in_use(host, port):
            logger.info(f"Found available port: {port}")
            return (port, False)
    
    logger.error(f"No available ports in range {start_port}-{end_port}")
    return (0, False)


def get_using_process(port: int) -> Optional[str]:
    """
    获取占用指定端口的进程信息（仅用于诊断）
    
    Note: 这个函数需要管理员权限才能完整工作
    """
    try:
        import psutil
        for conn in psutil.net_connections():
            if conn.laddr.port == port:
                try:
                    process = psutil.Process(conn.pid)
                    return f"PID: {conn.pid}, Process: {process.name()}"
                except:
                    return f"PID: {conn.pid}"
    except ImportError:
        logger.warning("psutil not available, cannot get process information")
    except Exception as e:
        logger.debug(f"Error getting process info for port {port}: {e}")
    
    return None


def check_port_and_warn(host: str, port: int) -> bool:
    """
    检查端口并在需要时显示警告信息
    
    Returns:
        True 如果端口可用，False 如果端口被占用
    """
    if is_port_in_use(host, port):
        logger.warning("=" * 60)
        logger.warning(f"WARNING: Port {port} is already in use!")
        logger.warning("=" * 60)
        
        process_info = get_using_process(port)
        if process_info:
            logger.warning(f"Port is being used by: {process_info}")
        
        logger.warning("")
        logger.warning("Possible solutions:")
        logger.warning("  1. Kill the process using the port")
        logger.warning("  2. Use a different port by setting GPU_MONITOR_PORT environment variable")
        logger.warning("  3. Enable automatic port selection (default: enabled)")
        logger.warning("=" * 60)
        
        return False
    
    return True
