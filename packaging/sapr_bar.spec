'''Собирает оконное приложение и отдельный переносимый EXE для Windows.'''

from pathlib import Path
import sys

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / 'src'))
from sapr.metadata import VERSION

icon = str(root / 'src' / 'sapr' / 'resources' / 'icons' / 'app.ico')
version = str(root / 'build' / 'version_info.txt')
analysis = Analysis(
    [str(root / 'packaging' / 'entry.py')],
    pathex=[str(root / 'src')],
    datas=[(str(root / 'src' / 'sapr' / 'resources'), 'sapr/resources'),
           (str(root / 'build' / 'licenses'), 'licenses'),
           (str(root / 'docs' / 'Руководство.txt'), 'docs')],
    hiddenimports=[],
    excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'numpy', 'scipy', 'pytest', 'PIL'],
    noarchive=False,
)
archive = PYZ(analysis.pure)
application = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name='SAPR BAR', console=False, icon=icon, version=version,
    upx=False, disable_windowed_traceback=False,
)
COLLECT(application, analysis.binaries, analysis.datas, name='SAPR BAR', upx=False)
EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas,
    name=f'SAPR-BAR-{VERSION}-portable', console=False,
    icon=icon, version=version, upx=False, disable_windowed_traceback=False,
)
