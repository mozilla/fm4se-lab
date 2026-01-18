"""
Custom logging configuration with colors and better formatting.
"""
import logging
import sys

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for terminal output."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m',       # Reset
        'BOLD': '\033[1m',        # Bold
        'DIM': '\033[2m',         # Dim
    }

    
    def format(self, record):
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            colored_level = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
            record.levelname = colored_level
        
        # Format the message
        if hasattr(record, 'is_header') and record.is_header:
            # Special formatting for headers
            msg = f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{'='*80}{self.COLORS['RESET']}"
            msg += f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{record.msg}{self.COLORS['RESET']}"
            msg += f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{'='*80}{self.COLORS['RESET']}"
            record.msg = msg
        elif hasattr(record, 'is_step') and record.is_step:
            # Special formatting for step headers
            msg = f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{'-'*80}{self.COLORS['RESET']}"
            msg += f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{record.msg}{self.COLORS['RESET']}"
            msg += f"\n{self.COLORS['BOLD']}{self.COLORS['INFO']}{'-'*80}{self.COLORS['RESET']}"
            record.msg = msg
        
        return super().format(record)


def setup_logging(log_file='bug_analyzer.log', level=logging.INFO):
    """
    Setup logging with colored console output and file output.
    
    Args:
        log_file: Path to log file
        level: Logging level
    """
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Remove existing handlers
    logger.handlers = []
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(
        '%(levelname)s %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # File handler without colors
    file_handler = logging.FileHandler(log_file, mode='w')  # Overwrite each run
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


class LoggerAdapter(logging.LoggerAdapter):
    """Custom logger adapter with helper methods for structured logging."""
    
    def header(self, msg):
        """Log a major section header."""
        self.info(msg, extra={'is_header': True})
    
    def step(self, msg):
        """Log a step header."""
        self.info(msg, extra={'is_step': True})
    
    def success(self, msg):
        """Log a success message."""
        self.info(f"✓ {msg}")
    
    def progress(self, msg):
        """Log a progress message."""
        self.info(f"→ {msg}")
    
    def data(self, key, value):
        """Log a key-value pair."""
        self.info(f"  {key}: {value}")

    def rule(self, style="-"):
        """Log a horizontal rule."""
        self.info(style * 80)

    def section(self, msg):
        """Log a section header."""
        self.info(f"\n>> {msg}")


def get_logger(name):
    """
    Get a logger with custom adapter.
    
    Args:
        name: Logger name
        
    Returns:
        LoggerAdapter instance
    """
    base_logger = logging.getLogger(name)
    return LoggerAdapter(base_logger, {})
