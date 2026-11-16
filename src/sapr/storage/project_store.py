'''Управляет папкой проекта и проверенными данными для процессора.'''

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

from ..domain import ModelValidationError, StructuralModel, validate_model
from .formats import ProjectFormatError, decode_sources, encode_sources
from .processed_formats import PROCESSED_FORMAT, decode_processed, encode_processed, processed_matches


@dataclass(frozen=True)
class Project:
    '''Описывает сохранённый проект.

    Attributes:
        path: Абсолютный путь к папке проекта.
        name: Название проекта.
        model: Текущие исходные данные.
        validated: Наличие актуальных проверенных файлов для процессора.
    '''

    path: Path
    name: str
    model: StructuralModel
    validated: bool = False

    @property
    def project_file(self) -> Path:
        '''Возвращает путь к файлу проекта KPR.'''
        return self.path / 'project.kpr'


class ProjectStore:
    '''Сохраняет внешний формат и формирует внутренний после диагностики.

    KPR содержит название, статус проверки и хеши исходных CN и LD.
    CNX и LDX содержат проверенные числовые массивы из исходных CN и LD.
    Оба представления ограничены последовательной осевой конструкцией.
    '''

    FILES = ('project.cn', 'project.ld', 'project.cnx', 'project.ldx', 'project.kpr')
    MAX_FILE_BYTES = 8 * 1024 * 1024

    def read_for_processor(self, project: Project) -> tuple[StructuralModel, str]:
        '''Читает согласованный снимок актуальных CNX и LDX после проверки.

        Args:
            project: Открытый проект с последней сохранённой моделью.

        Returns:
            Модель из обработанных файлов и отпечаток всех файлов проекта.

        Raises:
            ProjectFormatError: Проверка отсутствует, файлы устарели или изменены.
        '''
        folder = project.path.resolve()
        try:
            before = self.file_signature(folder)
            contents = {name: self._read_bytes(folder / name) for name in self.FILES}
            after = self.file_signature(folder)
            if before != after:
                raise ProjectFormatError('Файлы изменились во время чтения. Повторите проверку')
            times = {name: stamp for name, stamp, _ in after}
            if min(times['project.cnx'], times['project.ldx']) < max(times['project.cn'], times['project.ld']):
                raise ProjectFormatError('CNX и LDX устарели. Проверьте проект в препроцессоре')
            manifest = json.loads(contents['project.kpr'].decode('utf-8-sig'))
            self._validate_manifest(manifest)
            hashes = {name: sha256(contents[name]).hexdigest() for name in ('project.cn', 'project.ld')}
            if (manifest['validated'] is not True or manifest['sources'] != hashes
                    or manifest.get('prepared_format', PROCESSED_FORMAT) != PROCESSED_FORMAT):
                raise ProjectFormatError('Исходные данные не прошли актуальную проверку')
            source = decode_sources(contents['project.cn'].decode('utf-8-sig'), contents['project.ld'].decode('utf-8-sig'))
            cnx, ldx = contents['project.cnx'].decode('ascii'), contents['project.ldx'].decode('ascii')
            expected = encode_processed(source)
            if not processed_matches(cnx, expected[0]) or not processed_matches(ldx, expected[1]):
                raise ProjectFormatError('CNX и LDX не соответствуют исходным данным. Повторите проверку')
            model = decode_processed(cnx, ldx)
            if model != project.model:
                raise ProjectFormatError('Проект изменён вне приложения. Откройте его заново')
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProjectFormatError('Повреждены файлы проекта. Повторите проверку') from error
        fingerprint = sha256()
        for name in self.FILES:
            fingerprint.update(name.encode('ascii'))
            fingerprint.update(sha256(contents[name]).digest())
        fingerprint.update(repr(after).encode('ascii'))
        return model, fingerprint.hexdigest()

    def file_signature(self, folder: Path) -> tuple[tuple[str, int, int], ...]:
        '''Возвращает времена изменения и размеры файлов для контроля актуальности.'''
        values = []
        for name in self.FILES:
            try:
                stat = (folder / name).stat()
            except OSError as error:
                raise ProjectFormatError('Нет проверенных CNX и LDX. Проверьте проект в препроцессоре') from error
            values.append((name, stat.st_mtime_ns, stat.st_size))
        return tuple(values)

    def create(self, parent: Path, name: str) -> Project:
        '''Создаёт новую папку с пустым черновиком проекта.

        Args:
            parent: Родительская папка, которая будет создана при необходимости.
            name: Имя создаваемой папки и проекта.

        Returns:
            Сохранённый пустой проект.

        Raises:
            ProjectFormatError: Путь занят файлом или папка проекта уже существует.
            PermissionError: Не хватает прав для создания каталогов.
        '''
        name = self._validate_name(name)
        parent = Path(parent).expanduser().resolve()
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError) as error:
            raise ProjectFormatError('Родительский путь или его часть заняты файлом') from error
        except PermissionError as error:
            raise PermissionError('Недостаточно прав для создания родительской папки') from error
        folder = parent / name
        try:
            folder.mkdir(exist_ok=False)
        except FileExistsError as error:
            raise ProjectFormatError('По пути проекта уже существует файл или папка') from error
        except PermissionError as error:
            raise PermissionError('Недостаточно прав для создания папки проекта') from error
        project = Project(folder, name, StructuralModel())
        try:
            return self.save(project, project.model)
        except Exception:
            try:
                folder.rmdir()
            except OSError:
                pass
            raise

    def save(self, project: Project, model: StructuralModel, *, validate: bool = False) -> Project:
        '''Сохраняет исходные данные и при необходимости проверяет модель.

        Args:
            project: Проект с существующей папкой.
            model: Новые исходные данные.
            validate: Требование сформировать проверенные CNX и LDX.

        Returns:
            Обновлённый сохранённый проект.

        Raises:
            ModelValidationError: Диагностика завершилась с ошибками.
            ProjectFormatError: Невозможно представить данные в формате проекта.
        '''
        folder = Path(project.path).resolve()
        if not folder.is_dir():
            raise ProjectFormatError('Папка проекта не существует')
        name = self._validate_name(project.name)
        issues = validate_model(model) if validate else ()
        construction, loading = encode_sources(name, model)
        sources = {'project.cn': construction.encode('utf-8'), 'project.ld': loading.encode('utf-8')}
        passed = validate and not issues
        manifest = {
            'name': name, 'validated': passed,
            'sources': {key: sha256(value).hexdigest() for key, value in sources.items()},
        }
        contents = dict(sources)
        if passed:
            cnx, ldx = encode_processed(model)
            contents['project.cnx'] = cnx.encode('ascii')
            contents['project.ldx'] = ldx.encode('ascii')
        contents['project.kpr'] = self._json_bytes(manifest)
        self._write_transaction(folder, contents)
        if issues:
            raise ModelValidationError(issues)
        return Project(folder, name, model, passed)

    def load(self, path: Path) -> Project:
        '''Открывает папку проекта или его файл KPR.

        Args:
            path: Путь к папке или файлу проекта.

        Returns:
            Исходные данные и достоверный статус подготовленных файлов.

        Raises:
            ProjectFormatError: Файлы отсутствуют, повреждены или имеют другую версию.
        '''
        path = Path(path).expanduser().resolve()
        folder = path if path.is_dir() else path.parent
        if not path.is_dir() and path.name != 'project.kpr':
            raise ProjectFormatError('Выберите файл project.kpr или папку проекта')
        manifest = self._read_json(folder / 'project.kpr')
        name = self._validate_manifest(manifest)
        sources = {filename: self._read_bytes(folder / filename) for filename in ('project.cn', 'project.ld')}
        try:
            model = decode_sources(sources['project.cn'].decode('utf-8-sig'), sources['project.ld'].decode('utf-8-sig'))
        except UnicodeDecodeError as error:
            raise ProjectFormatError('Файлы исходных данных должны использовать UTF-8') from error
        hashes = {key: sha256(value).hexdigest() for key, value in sources.items()}
        validated = (manifest['validated'] and hashes == manifest.get('sources')
                     and manifest.get('prepared_format', PROCESSED_FORMAT) == PROCESSED_FORMAT
                     and not validate_model(model))
        if validated:
            expected_cnx, expected_ldx = encode_processed(model)
            try:
                validated = self._prepared_matches(folder / 'project.cnx', expected_cnx)
                validated = validated and self._prepared_matches(folder / 'project.ldx', expected_ldx)
            except ProjectFormatError:
                validated = False
        return Project(folder, name, model, bool(validated))

    @classmethod
    def _validate_manifest(cls, manifest: dict) -> str:
        '''Проверяет краткий KPR и служебные поля прежних проектов.

        Args:
            manifest: Данные JSON из файла проекта.

        Returns:
            Допустимое название проекта.

        Raises:
            ProjectFormatError: Обязательные поля повреждены или версия неизвестна.
        '''
        if not isinstance(manifest, dict):
            raise ProjectFormatError('KPR должен содержать объект JSON')
        if 'format' in manifest and manifest['format'] != 'sapr-bar-project':
            raise ProjectFormatError('Это не файл проекта САПР BAR')
        if 'version' in manifest and (type(manifest['version']) is not int or manifest['version'] != 1):
            raise ProjectFormatError('Версия файла проекта не поддерживается')
        if 'units' in manifest and manifest['units'] != 'SI':
            raise ProjectFormatError('Поддерживаются только единицы СИ')
        if type(manifest.get('validated')) is not bool:
            raise ProjectFormatError('Статус validated должен быть true или false')
        sources = manifest.get('sources')
        if (not isinstance(sources, dict) or set(sources) != {'project.cn', 'project.ld'}
                or any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None
                       for value in sources.values())):
            raise ProjectFormatError('В sources нужны хеши SHA256 файлов project.cn и project.ld')
        return cls._validate_name(manifest.get('name'))

    @staticmethod
    def _validate_name(name: str) -> str:
        '''Проверяет имя папки с учётом ограничений Windows.'''
        if not isinstance(name, str) or not name or len(name) > 78:
            raise ProjectFormatError('Название проекта должно содержать от 1 до 78 символов')
        if name != name.strip() or name.endswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            raise ProjectFormatError('Название содержит недопустимые для папки символы')
        reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
        if name in {'.', '..'} or name.split('.')[0].upper() in reserved:
            raise ProjectFormatError('Это название зарезервировано операционной системой')
        return name

    @staticmethod
    def _json_bytes(value: dict) -> bytes:
        '''Кодирует структуру проекта в UTF-8 с отступами.'''
        return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

    def _read_bytes(self, path: Path) -> bytes:
        '''Читает ограниченный по размеру обычный файл проекта.'''
        if path.is_symlink():
            raise ProjectFormatError('Файл проекта не должен быть символической ссылкой')
        try:
            with path.open('rb') as stream:
                content = stream.read(self.MAX_FILE_BYTES + 1)
        except OSError as error:
            raise ProjectFormatError(f'Не удалось прочитать {path.name}') from error
        if len(content) > self.MAX_FILE_BYTES:
            raise ProjectFormatError(f'Файл {path.name} превышает допустимый размер')
        return content

    def _read_json(self, path: Path) -> dict:
        '''Читает служебную структуру проекта с проверкой кодировки.'''
        try:
            return json.loads(self._read_bytes(path).decode('utf-8-sig'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProjectFormatError(f'Файл {path.name} содержит некорректный JSON') from error

    def _prepared_matches(self, path: Path, expected: str) -> bool:
        '''Сравнивает числовые обработанные данные с текущей моделью.'''
        try:
            actual = self._read_bytes(path).decode('ascii')
        except UnicodeDecodeError:
            return False
        return processed_matches(actual, expected)

    def _write_transaction(self, folder: Path, contents: dict[str, bytes]) -> None:
        '''Заменяет известные файлы с откатом при ошибке ввода вывода.'''
        for name in self.FILES:
            target = folder / name
            if target.is_symlink() or target.resolve().parent != folder:
                raise ProjectFormatError('Файл проекта выходит за пределы папки')
            if target.exists() and not target.is_file():
                raise ProjectFormatError(f'{name} должен быть обычным файлом')
        with tempfile.TemporaryDirectory(prefix='.save-', dir=folder) as temporary:
            stage = Path(temporary)
            original = {name for name in self.FILES if (folder / name).exists()}
            for name in original:
                shutil.copyfile(folder / name, stage / f'{name}.backup')
            for name, content in contents.items():
                if len(content) > self.MAX_FILE_BYTES:
                    raise ProjectFormatError(f'Файл {name} превышает допустимый размер')
                (stage / name).write_bytes(content)
            changed: list[str] = []
            try:
                for name in self.FILES:
                    target = folder / name
                    if name in contents:
                        (stage / name).replace(target)
                        changed.append(name)
                    elif target.exists():
                        target.unlink()
                        changed.append(name)
            except OSError:
                for name in reversed(changed):
                    target = folder / name
                    if name in original:
                        (stage / f'{name}.backup').replace(target)
                    else:
                        target.unlink(missing_ok=True)
                raise
