from collections import defaultdict
from pathlib import Path
from uuid import uuid4
import logging
from logging.config import dictConfig
import os
import time
import wandb


class WnBHandler(logging.Handler):
    '''Listen for W&B logs.

    Default Usage:
    ```
    logging.log(metrics_dict, extra=dict(metrics=True, prefix='train'))
    ```

    `metrics_dict` (optionally prefixed) is directly consumed by `wandb.log`.
    '''
    def emit(self, record):
        metrics = record.msg
        if hasattr(record, 'prefix'):
            metrics = {f'{record.prefix}/{k}': v for k, v in metrics.items()}
        wandb.log(metrics)


class MetricsFilter(logging.Filter):
    def __init__(self, extra_key='metrics', invert=False):
        super().__init__()
        self.extra_key = extra_key
        self.invert = invert

    def filter(self, record):
        should_pass = hasattr(record, self.extra_key) and getattr(record, self.extra_key)
        if self.invert:
            should_pass = not should_pass
        return should_pass


class MetricsFileHandler(logging.FileHandler):
    def emit(self, record):
        if hasattr(record, 'prefix'):
            record.msg = {f'{record.prefix}/{k}': v for k, v in record.msg.items()}
        record.msg['timestamp_ns'] = time.time_ns()
        return super().emit(record)

    
class TensorboardHandler(logging.Handler):
    from torch.utils.tensorboard import SummaryWriter

    def __init__(self, filename):
        super().__init__()

        self.writer = SummaryWriter(log_dir=filename)
        self.step_dict = defaultdict(int)

    def emit(self, record):
        if hasattr(record, 'prefix'):
            record.msg = {f'{record.prefix}/{k}': v for k, v in record.msg.items()}
        # record.msg['timestamp_ns'] = time.time_ns()

        for k, v in record.msg.items():
            self.step_dict[k] += 1
            self.writer.add_scalar(k, v, global_step=self.step_dict[k])

    def __del__(self):
        self.writer.close()
    

def get_log_dir(log_dir=None):
    if log_dir is not None:
        return Path(log_dir)

    root_dir = Path(os.environ.get('LOGDIR', Path.cwd() / '.log')) / Path.cwd().name / f'run-{str(uuid4())[:8]}'
    log_dir = Path(str((root_dir / 'files').resolve()))
    log_dir.mkdir(parents=True, exist_ok=True)

    return log_dir


def set_logging(log_dir=None, use_wandb=True, metrics_extra_key='metrics'):
    if use_wandb:
        ## Set other properties using environment variables: https://docs.wandb.ai/guides/track/environment-variables.
        wandb.init(
            mode=os.environ.get('WANDB_MODE', default='offline'),
            # settings=wandb.Settings(start_method="fork"),
        )
        log_dir = Path(wandb.run.dir)
    else:
        log_dir = get_log_dir(log_dir=log_dir)

    _CONFIG = {
        'version': 1,
        'formatters': {
            'console': {
                'format': '[%(asctime)s] (%(funcName)s:%(levelname)s) %(message)s',
            },
        },
        'filters': {
            'metrics': {
                '()': MetricsFilter,
                'extra_key': metrics_extra_key,
            },
            'nometrics': {
                '()': MetricsFilter,
                'extra_key': metrics_extra_key,
                'invert': True,
            },
        },
        'handlers': {
            'stdout': {
                '()': logging.StreamHandler,
                'formatter': 'console',
                'stream': 'ext://sys.stdout',
                'filters': ['nometrics'],
            },
            'metrics_file': {
                '()': MetricsFileHandler,
                'filename': str(Path(log_dir) / 'metrics.log'),
                'filters': ['metrics'],
            },
            'wandb_file': {
                '()': WnBHandler,
                'filters': ['metrics'],
            },
        },
        'loggers': {
            '': {
                'handlers': ['stdout', 'wandb_file' if use_wandb else 'metrics_file'],
                'level': os.environ.get('LOGLEVEL', 'INFO'),
            },
        },
    }

    dictConfig(_CONFIG)

    logging.info(f'Files stored in "{log_dir}".')

    def finish_logging():
        if use_wandb:
            wandb.finish()

    return log_dir, finish_logging
