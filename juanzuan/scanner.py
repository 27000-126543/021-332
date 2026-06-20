import os
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from collections import defaultdict

from .config import parse_filename, get_project_type, normalize_date


@dataclass
class FileInfo:
    path: str
    filename: str
    size: int
    unit: str = None
    category_code: str = None
    category_name: str = None
    date: str = None
    number: str = None
    is_recognized: bool = False
    file_hash: str = None


@dataclass
class ScanResult:
    files: List[FileInfo] = field(default_factory=list)
    recognized_files: List[FileInfo] = field(default_factory=list)
    unrecognized_files: List[FileInfo] = field(default_factory=list)
    grouped_by_unit: Dict[str, List[FileInfo]] = field(default_factory=dict)
    grouped_by_category: Dict[str, List[FileInfo]] = field(default_factory=dict)
    duplicates: Dict[str, List[FileInfo]] = field(default_factory=dict)
    total_count: int = 0
    recognized_count: int = 0
    unrecognized_count: int = 0


def calculate_file_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, OSError):
        return ""


def scan_project(project_path: str, project_type: str, calculate_hash: bool = False) -> ScanResult:
    result = ScanResult()

    if not os.path.exists(project_path):
        raise FileNotFoundError(f"项目路径不存在: {project_path}")

    if not os.path.isdir(project_path):
        raise NotADirectoryError(f"项目路径不是目录: {project_path}")

    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    hash_to_files = defaultdict(list)

    for root, dirs, files in os.walk(project_path):
        for filename in files:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, project_path)

            try:
                file_size = os.path.getsize(filepath)
            except (IOError, OSError):
                file_size = 0

            file_hash = None
            if calculate_hash:
                file_hash = calculate_file_hash(filepath)
                if file_hash:
                    hash_to_files[file_hash].append(filepath)

            parsed = parse_filename(filename, project_type)

            file_info = FileInfo(
                path=rel_path,
                filename=filename,
                size=file_size,
                unit=parsed["unit"],
                category_code=parsed["category_code"],
                category_name=parsed["category_name"],
                date=normalize_date(parsed["date"]),
                number=parsed["number"],
                is_recognized=parsed["is_recognized"],
                file_hash=file_hash,
            )

            result.files.append(file_info)

            if parsed["is_recognized"]:
                result.recognized_files.append(file_info)
            else:
                result.unrecognized_files.append(file_info)

            unit_key = parsed["unit"] or "未识别单位工程"
            if unit_key not in result.grouped_by_unit:
                result.grouped_by_unit[unit_key] = []
            result.grouped_by_unit[unit_key].append(file_info)

            cat_key = parsed["category_code"] or "未分类"
            if cat_key not in result.grouped_by_category:
                result.grouped_by_category[cat_key] = []
            result.grouped_by_category[cat_key].append(file_info)

    result.total_count = len(result.files)
    result.recognized_count = len(result.recognized_files)
    result.unrecognized_count = len(result.unrecognized_files)

    for file_hash, filepaths in hash_to_files.items():
        if len(filepaths) > 1:
            dup_files = []
            for fp in filepaths:
                rel_fp = os.path.relpath(fp, project_path)
                for fi in result.files:
                    if fi.path == rel_fp:
                        dup_files.append(fi)
                        break
            result.duplicates[file_hash] = dup_files

    return result


def generate_checklist(scan_result: ScanResult, project_path: str, output_path: str, project_type: str) -> str:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    os.makedirs(output_path, exist_ok=True)

    checklist_path = os.path.join(output_path, "待确认文件清单.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 待确认文件清单")
    lines.append("=" * 80)
    lines.append(f"项目路径: {project_path}")
    lines.append(f"工程类型: {pt.name}")
    lines.append(f"文件总数: {scan_result.total_count}")
    lines.append(f"已识别: {scan_result.recognized_count}")
    lines.append(f"待确认: {scan_result.unrecognized_count}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("说明:")
    lines.append("  1. 请在每行文件的【案卷类别】处填写对应的案卷编号")
    lines.append("  2. 可用的案卷编号参考下方'案卷类别对照表'")
    lines.append("  3. 标记为作废的文件请填写【作废】")
    lines.append("  4. 修改后保存，然后运行 organize 命令完成重排")
    lines.append("-" * 80)
    lines.append("")
    lines.append("案卷类别对照表:")
    for vc in pt.volume_categories:
        lines.append(f"  {vc.code} - {vc.name}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("待确认文件列表")
    lines.append("=" * 80)
    lines.append("")

    if scan_result.unrecognized_count == 0:
        lines.append("（无不识别文件，所有文件均已自动分类）")
    else:
        for idx, fi in enumerate(scan_result.unrecognized_files, 1):
            lines.append(f"[{idx:04d}] 文件名: {fi.filename}")
            lines.append(f"       相对路径: {fi.path}")
            lines.append(f"       文件大小: {fi.size} 字节")
            lines.append(f"       识别到的单位工程: {fi.unit or '无'}")
            lines.append(f"       识别到的日期: {fi.date or '无'}")
            lines.append(f"       识别到的编号: {fi.number or '无'}")
            lines.append(f"       【案卷类别】: ____")
            lines.append(f"       【备注】: ")
            lines.append("")

    lines.append("")
    lines.append("=" * 80)
    lines.append("已识别文件统计（供参考）")
    lines.append("=" * 80)
    lines.append("")

    for cat_code, files in sorted(scan_result.grouped_by_category.items()):
        if cat_code == "未分类":
            continue
        cat_name = ""
        for vc in pt.volume_categories:
            if vc.code == cat_code:
                cat_name = vc.name
                break
        lines.append(f"  {cat_code} - {cat_name}: {len(files)} 个文件")

    lines.append("")
    lines.append("=" * 80)
    lines.append("按单位工程统计")
    lines.append("=" * 80)
    lines.append("")

    for unit, files in sorted(scan_result.grouped_by_unit.items()):
        lines.append(f"  {unit}: {len(files)} 个文件")

    with open(checklist_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return checklist_path


def generate_preliminary_list(scan_result: ScanResult, output_path: str, project_type: str) -> str:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    os.makedirs(output_path, exist_ok=True)

    list_path = os.path.join(output_path, "初步分组清单.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 初步分组清单")
    lines.append("=" * 80)
    lines.append(f"工程类型: {pt.name}")
    lines.append(f"文件总数: {scan_result.total_count}")
    lines.append(f"已识别: {scan_result.recognized_count}")
    lines.append(f"待确认: {scan_result.unrecognized_count}")
    lines.append("")

    for cat_code in sorted(scan_result.grouped_by_category.keys()):
        if cat_code == "未分类":
            continue

        files = scan_result.grouped_by_category[cat_code]
        cat_name = ""
        for vc in pt.volume_categories:
            if vc.code == cat_code:
                cat_name = vc.name
                break

        lines.append("-" * 80)
        lines.append(f"【{cat_code}】{cat_name}  ({len(files)}个文件)")
        lines.append("-" * 80)

        files_sorted = sorted(files, key=lambda x: (x.unit or "", x.date or "", x.number or ""))

        for idx, fi in enumerate(files_sorted, 1):
            unit_info = f"[{fi.unit}]" if fi.unit else ""
            date_info = f"({fi.date})" if fi.date else ""
            num_info = f"-{fi.number}" if fi.number else ""
            lines.append(f"  {idx:03d}. {unit_info}{date_info}{num_info} {fi.filename}")

        lines.append("")

    lines.append("-" * 80)
    lines.append(f"【未分类】 ({scan_result.unrecognized_count}个文件)")
    lines.append("-" * 80)
    for idx, fi in enumerate(scan_result.unrecognized_files, 1):
        lines.append(f"  {idx:03d}. {fi.filename}")
    lines.append("")

    with open(list_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return list_path


def generate_duplicate_list(scan_result: ScanResult, output_path: str) -> str:
    os.makedirs(output_path, exist_ok=True)

    list_path = os.path.join(output_path, "重复文件清单.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 重复文件清单")
    lines.append("=" * 80)
    lines.append(f"重复文件组数: {len(scan_result.duplicates)}")
    lines.append("")

    if not scan_result.duplicates:
        lines.append("（未检测到重复文件）")
    else:
        for idx, (file_hash, files) in enumerate(scan_result.duplicates.items(), 1):
            lines.append(f"[{idx:03d}] 文件哈希: {file_hash[:16]}...")
            lines.append(f"       重复数量: {len(files)} 个")
            for fi in files:
                lines.append(f"       - {fi.path}  ({fi.size} 字节)")
            lines.append("")

    with open(list_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return list_path
