import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from .config import get_project_type, parse_filename, normalize_date
from .scanner import FileInfo, scan_project, generate_duplicate_list


@dataclass
class CheckedFile:
    path: str
    filename: str
    category_code: str = None
    category_name: str = None
    is_void: bool = False
    remark: str = ""


@dataclass
class OrganizeResult:
    total_files: int = 0
    organized_files: int = 0
    void_files: int = 0
    skipped_files: int = 0
    volume_folders: List[str] = field(default_factory=list)
    missing_categories: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def parse_checklist(checklist_path: str) -> List[CheckedFile]:
    checked_files = []

    if not os.path.exists(checklist_path):
        raise FileNotFoundError(f"核对清单不存在: {checklist_path}")

    with open(checklist_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(
        r'\[\d+\]\s*文件名:\s*(?P<filename>.+?)\s*\n'
        r'\s*相对路径:\s*(?P<path>.+?)\s*\n'
        r'(?:.*?\n)*?'
        r'\s*【案卷类别】:\s*(?P<category>.*?)\s*\n'
        r'\s*【备注】:\s*(?P<remark>.*?)\s*\n',
        re.MULTILINE
    )

    for match in pattern.finditer(content):
        filename = match.group("filename").strip()
        path = match.group("path").strip()
        category = match.group("category").strip()
        remark = match.group("remark").strip()

        is_void = category in ["作废", "void", "VOID", "废"]
        category_code = None
        category_name = None

        if not is_void and category and category != "____":
            category_code = category.strip()

        checked_files.append(CheckedFile(
            path=path,
            filename=filename,
            category_code=category_code,
            category_name=category_name,
            is_void=is_void,
            remark=remark,
        ))

    return checked_files


def merge_with_scan(scan_files: List[FileInfo], checked_files: List[CheckedFile], 
                    project_type: str) -> List[FileInfo]:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    checked_map = {}
    for cf in checked_files:
        checked_map[cf.path] = cf

    result = []
    for fi in scan_files:
        if fi.path in checked_map:
            cf = checked_map[fi.path]
            if cf.is_void:
                new_fi = FileInfo(
                    path=fi.path,
                    filename=fi.filename,
                    size=fi.size,
                    unit=fi.unit,
                    category_code="作废",
                    category_name="作废文件",
                    date=fi.date,
                    number=fi.number,
                    is_recognized=True,
                    file_hash=fi.file_hash,
                )
                result.append(new_fi)
            elif cf.category_code:
                cat_name = ""
                for vc in pt.volume_categories:
                    if vc.code == cf.category_code:
                        cat_name = vc.name
                        break
                new_fi = FileInfo(
                    path=fi.path,
                    filename=fi.filename,
                    size=fi.size,
                    unit=fi.unit,
                    category_code=cf.category_code,
                    category_name=cat_name or cf.category_code,
                    date=fi.date,
                    number=fi.number,
                    is_recognized=True,
                    file_hash=fi.file_hash,
                )
                result.append(new_fi)
            else:
                result.append(fi)
        else:
            result.append(fi)

    return result


def organize_files(project_path: str, output_path: str, files: List[FileInfo],
                   project_type: str, copy_mode: bool = True) -> OrganizeResult:
    result = OrganizeResult()
    result.total_files = len(files)

    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    os.makedirs(output_path, exist_ok=True)

    void_dir = os.path.join(output_path, "00_作废文件")
    unclassified_dir = os.path.join(output_path, "01_待分类文件")

    volume_files = defaultdict(list)

    for fi in files:
        if fi.category_code == "作废":
            volume_files["作废"].append(fi)
        elif fi.category_code:
            volume_files[fi.category_code].append(fi)
        else:
            volume_files["未分类"].append(fi)

    all_categories = {vc.code for vc in pt.volume_categories}
    present_categories = set()

    for cat_code, cat_files in sorted(volume_files.items()):
        if cat_code == "作废":
            target_dir = void_dir
            result.void_files = len(cat_files)
        elif cat_code == "未分类":
            target_dir = unclassified_dir
            result.skipped_files = len(cat_files)
        else:
            cat_name = ""
            for vc in pt.volume_categories:
                if vc.code == cat_code:
                    cat_name = vc.name
                    break
            folder_name = f"{cat_code}_{cat_name}" if cat_name else cat_code
            target_dir = os.path.join(output_path, folder_name)
            result.volume_folders.append(folder_name)
            present_categories.add(cat_code)
            result.organized_files += len(cat_files)

        os.makedirs(target_dir, exist_ok=True)

        cat_files_sorted = sorted(cat_files, key=lambda x: (x.unit or "", x.date or "", x.number or ""))

        for idx, fi in enumerate(cat_files_sorted, 1):
            src = os.path.join(project_path, fi.path)
            if not os.path.exists(src):
                result.errors.append(f"源文件不存在: {fi.path}")
                continue

            ext = os.path.splitext(fi.filename)[1]
            unit_prefix = f"[{fi.unit}]_" if fi.unit else ""
            new_filename = f"{idx:04d}_{unit_prefix}{fi.filename}"

            dst = os.path.join(target_dir, new_filename)

            try:
                if copy_mode:
                    shutil.copy2(src, dst)
                else:
                    shutil.move(src, dst)
            except (IOError, OSError) as e:
                result.errors.append(f"处理文件失败 {fi.path}: {str(e)}")

    result.missing_categories = sorted(all_categories - present_categories)

    return result


def generate_volume_catalog(output_path: str, project_type: str) -> str:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    catalog_path = os.path.join(output_path, "卷内目录.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 卷内总目录")
    lines.append("=" * 80)
    lines.append(f"工程类型: {pt.name}")
    lines.append("")

    volume_dirs = []
    void_dir = None
    unclassified_dir = None

    if os.path.isdir(output_path):
        for item in sorted(os.listdir(output_path)):
            item_path = os.path.join(output_path, item)
            if os.path.isdir(item_path):
                if item == "00_作废文件":
                    void_dir = item
                elif item == "01_待分类文件":
                    unclassified_dir = item
                elif item.startswith("00_") or item.startswith("01_"):
                    pass
                else:
                    volume_dirs.append(item)

    total_count = 0
    total_volumes = 0

    for volume_dir in volume_dirs:
        volume_path = os.path.join(output_path, volume_dir)
        files = [f for f in os.listdir(volume_path) if os.path.isfile(os.path.join(volume_path, f))]
        file_count = len(files)
        total_count += file_count
        total_volumes += 1

        lines.append(f"卷 {total_volumes:02d}: {volume_dir}")
        lines.append(f"       文件数: {file_count}")
        lines.append(f"       目录文件: {volume_dir}/卷内目录.txt")
        lines.append("")

        vol_catalog_path = os.path.join(volume_path, "卷内目录.txt")
        vol_lines = []
        vol_lines.append("=" * 60)
        vol_lines.append(f"卷内目录 - {volume_dir}")
        vol_lines.append("=" * 60)
        vol_lines.append(f"工程类型: {pt.name}")
        vol_lines.append("")
        vol_lines.append(f"{'序号':<8}{'文件名':<50}{'备注':<20}")
        vol_lines.append("-" * 80)

        for idx, filename in enumerate(sorted(files), 1):
            vol_lines.append(f"{idx:<8}{filename:<50}{'':<20}")

        vol_lines.append("")
        vol_lines.append(f"本卷共 {file_count} 份文件")

        with open(vol_catalog_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(vol_lines))

    lines.append("-" * 80)
    lines.append(f"合计: {total_volumes} 卷, {total_count} 份文件")
    lines.append("")

    if void_dir:
        void_path = os.path.join(output_path, void_dir)
        void_files = [f for f in os.listdir(void_path) if os.path.isfile(os.path.join(void_path, f))]
        lines.append(f"作废文件: {len(void_files)} 份 (位于 {void_dir}/)")

    if unclassified_dir:
        unc_path = os.path.join(output_path, unclassified_dir)
        unc_files = [f for f in os.listdir(unc_path) if os.path.isfile(os.path.join(unc_path, f))]
        lines.append(f"待分类文件: {len(unc_files)} 份 (位于 {unclassified_dir}/)")

    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return catalog_path


def generate_missing_report(output_path: str, project_type: str, missing_categories: List[str]) -> str:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    report_path = os.path.join(output_path, "缺项统计.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 缺项统计报告")
    lines.append("=" * 80)
    lines.append(f"工程类型: {pt.name}")
    lines.append("")

    total_categories = len(pt.volume_categories)
    missing_count = len(missing_categories)
    present_count = total_categories - missing_count

    lines.append(f"应有的案卷类别总数: {total_categories}")
    lines.append(f"已有的案卷类别数: {present_count}")
    lines.append(f"缺失的案卷类别数: {missing_count}")
    lines.append(f"完成率: {present_count/total_categories*100:.1f}%" if total_categories > 0 else "完成率: N/A")
    lines.append("")

    lines.append("-" * 80)
    lines.append("缺失的案卷类别:")
    lines.append("-" * 80)

    if missing_count == 0:
        lines.append("  （无缺失，所有案卷类别均有文件）")
    else:
        for cat_code in missing_categories:
            cat_name = ""
            for vc in pt.volume_categories:
                if vc.code == cat_code:
                    cat_name = vc.name
                    break
            lines.append(f"  {cat_code} - {cat_name}")

    lines.append("")
    lines.append("-" * 80)
    lines.append("全部案卷类别清单（供核对）:")
    lines.append("-" * 80)

    for vc in pt.volume_categories:
        status = "✓" if vc.code not in missing_categories else "✗"
        lines.append(f"  {status} {vc.code} - {vc.name}")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return report_path


def generate_summary_report(output_path: str, organize_result: OrganizeResult, 
                            project_type: str) -> str:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    report_path = os.path.join(output_path, "组卷汇总报告.txt")

    lines = []
    lines.append("=" * 80)
    lines.append("竣工资料组卷 - 汇总报告")
    lines.append("=" * 80)
    lines.append(f"工程类型: {pt.name}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("处理统计:")
    lines.append(f"  文件总数: {organize_result.total_files}")
    lines.append(f"  已组卷文件: {organize_result.organized_files}")
    lines.append(f"  作废文件: {organize_result.void_files}")
    lines.append(f"  待分类文件: {organize_result.skipped_files}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("案卷清单:")
    for vol in organize_result.volume_folders:
        lines.append(f"  {vol}")
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"缺失案卷类别数: {len(organize_result.missing_categories)}")
    if organize_result.missing_categories:
        for cat in organize_result.missing_categories:
            lines.append(f"  - {cat}")
    lines.append("")

    if organize_result.errors:
        lines.append("-" * 80)
        lines.append("错误信息:")
        for err in organize_result.errors:
            lines.append(f"  ! {err}")
        lines.append("")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return report_path
