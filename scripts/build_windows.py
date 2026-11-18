'''Собирает автономное приложение и пользовательский установщик Windows.'''

import argparse
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sapr.metadata import AUTHOR, NAME, VERSION
from sapr.domain import validate_model
from sapr.storage import ProjectStore
from sapr.storage.json_project import write_project_json


def prepare_version() -> None:
    '''Записывает сведения об авторе и версии в ресурсы исполняемых файлов.'''
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    version = tuple(map(int, VERSION.split('.'))) + (0,)
    fields = {
        'CompanyName': AUTHOR,
        'FileDescription': NAME,
        'FileVersion': VERSION,
        'InternalName': 'SAPR BAR',
        'OriginalFilename': 'SAPR BAR.exe',
        'ProductName': NAME,
        'ProductVersion': VERSION,
        'LegalCopyright': AUTHOR,
    }
    resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f,
                         flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('040904B0', [StringStruct(key, value)
                                                    for key, value in fields.items()])]),
              VarFileInfo([VarStruct('Translation', [0x409, 1200])])],
    )
    (ROOT / 'build' / 'version_info.txt').write_text(str(resource), encoding='utf-8')


def prepare_examples() -> None:
    '''Готовит проекты и JSON учебных задач из одного набора исходных данных.'''
    sources = ROOT / 'Проекты' / 'Единичные'
    target = ROOT / 'build' / 'examples'
    if target.is_symlink() or target.resolve() != ROOT / 'build' / 'examples':
        raise ValueError('Папка примеров должна находиться внутри каталога сборки')
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    store = ProjectStore()
    names = [f'Простая задача {number:02d}' for number in range(1, 6)]
    names.extend(f'Задача {number:02d}' for number in range(1, 7))
    names.append('Задача КР')
    projects = target / 'Единичные'
    json_folder = target / 'JSON' / 'Единичные'
    json_folder.mkdir(parents=True)
    for name in names:
        project = store.load(sources / name)
        issues = validate_model(project.model)
        if issues:
            raise ValueError(f'{name}: {issues[0].message}')
        store.create(projects, name, model=project.model)
        write_project_json(json_folder / f'{name}.json', project.model)
    shutil.copy2(sources / 'Параметры.txt', projects)


def prepare_notices() -> None:
    '''Включает доступные тексты лицензий зависимостей и их точные версии.'''
    target = ROOT / 'build' / 'licenses'
    target.mkdir(exist_ok=True)
    lines = [f'{NAME} {VERSION}', f'Автор приложения: {AUTHOR}', '',
             'Компоненты среды выполнения:', f'Python {sys.version.split()[0]}']
    for name in ('PyQt6', 'PyQt6-Qt6', 'PyQt6-sip'):
        package = distribution(name)
        lines.append(f'{name} {package.version}')
        for file in package.files or ():
            if file.name.upper().startswith(('LICENSE', 'COPYING')):
                source = Path(package.locate_file(file))
                if source.is_file():
                    shutil.copy2(source, target / f'{name}-{file.name}.txt')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, target / 'Python-LICENSE.txt')
    lines.extend(('', 'Сведения о компонентах:', 'https://www.python.org/',
                  'https://www.riverbankcomputing.com/software/pyqt/',
                  'https://www.qt.io/'))
    (target / 'Компоненты.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    '''Выполняет сборку и записывает контрольные суммы двух дистрибутивов.'''
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, required=True, help='Путь к ISCC.exe из Inno Setup 7')
    arguments = parser.parse_args()
    compiler = arguments.iscc.resolve()
    if not compiler.is_file():
        parser.error('Не найден компилятор Inno Setup')
    if sys.platform != 'win32':
        parser.error('Сборка EXE выполняется в Windows')
    (ROOT / 'build').mkdir(exist_ok=True)
    prepare_version()
    prepare_examples()
    prepare_notices()
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    str(ROOT / 'packaging' / 'sapr_bar.spec')], cwd=ROOT, check=True)
    subprocess.run([str(compiler), f'/DAppVersion={VERSION}', f'/DAppPublisher={AUTHOR}',
                    str(ROOT / 'packaging' / 'setup.iss')], cwd=ROOT, check=True)
    packages = sorted((ROOT / 'dist').glob(f'SAPR-BAR-{VERSION}-*.exe'))
    checksums = [f'{sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in packages]
    (ROOT / 'dist' / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='ascii')
    print('\n'.join(str(path) for path in packages))


if __name__ == '__main__':
    main()
