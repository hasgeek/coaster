__all__ = ['__version__', '__version_info__']

# When updating this number, also update docs/conf.py
__version__ = '0.6.dev0'
__version_info__ = tuple([int(num) if num.isdigit() else num for num in __version__.replace('-', '.', 1).split('.')])
