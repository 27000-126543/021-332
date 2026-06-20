import os
import re
import csv
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

from .config import get_project_type, parse_filename, normalize_date
from .scanner import FileInfo, scan_project, generate_duplicate_list, ScanResult


@dataclass
class BatchRule:
    rule_type: str
    rule_content: str
    category_code: str
    remark: str = ""

    def match(self, fi: FileInfo) -> bool:
        if self.rule_type == "KEYWORD":
            return self.rule_content.lower() in fi.filename.lower()
        elif self.rule_type == "SUBDIR":
            if not fi.subdir:
                return False
            sd_parts = fi.subdir.replace("\\", "/").split("/")
            return any(self.rule_content in sd for sd in sd_parts) or self.rule_content in fi.subdir
        return False


@dataclass
class CheckedFile:
    path: str
    filename: str
    category_code: str = None
    category_name: str = None
    is_void: bool = False
    remark: str = ""


@dataclass
class FileAction:
    source: str
    destination: str
    new_filename: str
    category_code: str
    category_name: str
    is_void: bool = False
    is_unclassified: bool = False


@dataclass
class OrganizeResult:
    total_files: int = 0
    organized_files: int = 0
    void_files: int = 0
    skipped_files: int = 0
    volume_folders: List[str] = field(default_factory=list)
    missing_categories: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    actions: List[FileAction] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)


def parse_batch_rules(checklist_content: str) -> List[BatchRule]:
    rules = []

    start_marker = "在此行下面添加您的批量归类规则"
    end_marker = "待确认文件列表"

    start_idx = checklist_content.find(start_marker)
    end_idx = checklist_content.find(end_marker)

    if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
        return rules

    rules_section = checklist_content[start_idx:end_idx]
    lines = rules_section.split('\n')

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        parts = stripped.split('|')
        if len(parts) >= 3:
            rtype = parts[0].strip().upper()
            rcontent = parts[1].strip()
            rcat = parts[2].strip()
            rremark = parts[3].strip() if len(parts) >= 4 else ""
            if rtype in ("KEYWORD", "SUBDIR") and rcontent and rcat:
                rules.append(BatchRule(
                    rule_type=rtype,
                    rule_content=rcontent,
                    category_code=rcat,
                    remark=rremark
                ))
    return rules


def parse_checklist(checklist_path: str) -> Tuple[List[CheckedFile], List[BatchRule]]:
    checked_files = []

    if not os.path.exists(checklist_path):
        raise FileNotFoundError(f"核对清单不存在: {checklist_path}")

    with open(checklist_path, 'r', encoding='utf-8') as f:
        content = f.read()

    batch_rules = parse_batch_rules(content)

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

    return checked_files, batch_rules


def apply_batch_rules(files: List[FileInfo], batch_rules: List[BatchRule]) -> Dict[str, str]:
    path_to_category = {}
    if not batch_rules:
        return path_to_category

    for rule in batch_rules:
        for fi in files:
            if fi.path in path_to_category:
                continue
            if rule.match(fi):
                path_to_category[fi.path] = rule.category_code
    return path_to_category


def merge_with_scan(scan_files: List[FileInfo], checked_files: List[CheckedFile],
                    batch_rules: List[BatchRule], project_type: str) -> List[FileInfo]:
    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

    rule_assignments = apply_batch_rules(scan_files, batch_rules)

    checked_map = {}
    for cf in checked_files:
        checked_map[cf.path] = cf

    result = []
    for fi in scan_files:
        new_cat_code = None
        new_cat_name = None
        is_void = False

        if fi.path in rule_assignments:
            rc = rule_assignments[fi.path]
            if rc == "作废":
                is_void = True
            else:
                new_cat_code = rc

        if fi.path in checked_map:
            cf = checked_map[fi.path]
            if cf.is_void:
                is_void = True
            elif cf.category_code:
                new_cat_code = cf.category_code

        if is_void:
            new_fi = FileInfo(
                path=fi.path, filename=fi.filename, size=fi.size,
                unit=fi.unit, category_code="作废", category_name="作废文件",
                date=fi.date, number=fi.number, is_recognized=True,
                file_hash=fi.file_hash, subdir=fi.subdir,
            )
            result.append(new_fi)
        elif new_cat_code:
            cat_name = new_cat_code
            for vc in pt.volume_categories:
                if vc.code == new_cat_code:
                    cat_name = vc.name
                    break
            new_fi = FileInfo(
                path=fi.path, filename=fi.filename, size=fi.size,
                unit=fi.unit, category_code=new_cat_code, category_name=cat_name,
                date=fi.date, number=fi.number, is_recognized=True,
                file_hash=fi.file_hash, subdir=fi.subdir,
            )
            result.append(new_fi)
        else:
            result.append(fi)

    return result


def build_action_plan(project_path: str, output_path: str, files: List[FileInfo],
                      project_type: str) -> Tuple[OrganizeResult, Dict[str, List[FileInfo]]]:
    result = OrganizeResult()
    result.total_files = len(files)

    pt = get_project_type(project_type)
    if not pt:
        raise ValueError(f"不支持的工程类型: {project_type}")

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
    cat_counts = {}

    for cat_code, cat_files in sorted(volume_files.items()):
        if cat_code == "作废":
            target_dir = void_dir
            result.void_files = len(cat_files)
            folder_display = "00_作废文件"
        elif cat_code == "未分类":
            target_dir = unclassified_dir
            result.skipped_files = len(cat_files)
            folder_display = "01_待分类文件"
        else:
            cat_name = ""
            for vc in pt.volume_categories:
                if vc.code == cat_code:
                    cat_name = vc.name
                    break
            folder_name = f"{cat_code}_{cat_name}" if cat_name else cat_code
            target_dir = os.path.join(output_path, folder_name)
            folder_display = folder_name
            result.volume_folders.append(folder_name)
            present_categories.add(cat_code)
            result.organized_files += len(cat_files)
            cat_counts[cat_code] = len(cat_files)

        cat_files_sorted = sorted(cat_files, key=lambda x: (x.unit or "", x.date or "", x.number or ""))

        for idx, fi in enumerate(cat_files_sorted, 1):
            src = os.path.join(project_path, fi.path)
            unit_prefix = f"[{fi.unit}]_" if fi.unit else ""
            new_filename = f"{idx:04d}_{unit_prefix}{fi.filename}"
            dst = os.path.join(target_dir, new_filename)

            action = FileAction(
                source=fi.path,
                destination=os.path.relpath(dst, output_path),
                new_filename=new_filename,
                category_code=cat_code,
                category_name=folder_display,
                is_void=(cat_code == "作废"),
                is_unclassified=(cat_code == "未分类"),
            )
            result.actions.append(action)

    result.category_counts = cat_counts
    result.missing_categories = sorted(all_categories - present_categories)

    return result, volume_files


def print_preview(result: OrganizeResult):
    print("")
    print("=" * 60)
    print("【预览】文件处理计划")
    print("=" * 60)
    print(f"文件总数: {result.total_files}")
    print(f"  - 已组卷: {result.organized_files}")
    print(f"  - 作废: {result.void_files}")
    print(f"  - 待分类: {result.skipped_files}")
    print("")
    print("-" * 60)
    print("案卷分配:")
    for vf in result.volume_folders:
        print(f"  ✓ {vf}")
    if result.missing_categories:
        print("")
        print(f"缺失案卷类别 ({len(result.missing_categories)}个):")
        for mc in result.missing_categories:
            print(f"  ✗ {mc}")
    print("")
    print("-" * 60)
    print("处理明细 (前20条):")
    for i, action in enumerate(result.actions[:20], 1):
        tag = "[作废]" if action.is_void else ("[待分类]" if action.is_unclassified else "")
        print(f"  {i:03d}. {action.source} -> {action.destination} {tag}")
    if len(result.actions) > 20:
        print(f"  ... 还有 {len(result.actions) - 20} 条记录")
    print("=" * 60)


def execute_actions(project_path: str, output_path: str, result: OrganizeResult,
                    copy_mode: bool = True) -> OrganizeResult:
    os.makedirs(output_path, exist_ok=True)

    dir_cache = set()

    for action in result.actions:
        src = os.path.join(project_path, action.source)
        dst = os.path.join(output_path, action.destination)

        dst_dir = os.path.dirname(dst)
        if dst_dir not in dir_cache:
            os.makedirs(dst_dir, exist_ok=True)
            dir_cache.add(dst_dir)

        if not os.path.exists(src):
            result.errors.append(f"源文件不存在: {action.source}")
            continue

        try:
            if copy_mode:
                shutil.copy2(src, dst)
            else:
                shutil.move(src, dst)
        except (IOError, OSError) as e:
            result.errors.append(f"处理文件失败 {action.source}: {str(e)}")

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
        files = [f for f in os.listdir(volume_path) if os.path.isfile(os.path.join(volume_path, f)) and f != "卷内目录.txt"]
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
        vol_lines.append(f"{'序号':<8}{'原文件名':<50}{'新文件名':<60}{'备注':<20}")
        vol_lines.append("-" * 140)

        all_volume_files = sorted([f for f in os.listdir(volume_path) if os.path.isfile(os.path.join(volume_path, f))])
        for idx, filename in enumerate(all_volume_files, 1):
            if filename == "卷内目录.txt":
                continue
            vol_lines.append(f"{idx:<8}{'':<50}{filename:<60}{'':<20}")

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
        lines.append(f"  {status} {vc.code:<4} - {vc.name}")

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
    lines.append("各案卷文件数:")
    for vc in pt.volume_categories:
        cnt = organize_result.category_counts.get(vc.code, 0)
        mark = " ✓" if cnt > 0 else " ✗"
        lines.append(f"  {vc.code:<4} - {vc.name}: {cnt}{mark}")
    lines.append("")
    lines.append("-" * 80)
    lines.append(f"缺失案卷类别数: {len(organize_result.missing_categories)}")
    if organize_result.missing_categories:
        for cat in organize_result.missing_categories:
            cat_name = ""
            for vc in pt.volume_categories:
                if vc.code == cat:
                    cat_name = vc.name
                    break
            lines.append(f"  - {cat} {cat_name}")
    lines.append("")

    if organize_result.errors:
        lines.append("-" * 80)
        lines.append(f"错误信息 ({len(organize_result.errors)}条):")
        for err in organize_result.errors:
            lines.append(f"  ! {err}")
        lines.append("")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return report_path


def generate_monthly_summary(project_results: List[Dict], output_path: str) -> Tuple[str, str, str, str]:
    os.makedirs(output_path, exist_ok=True)

    txt_path = os.path.join(output_path, "月底汇总表.txt")
    csv_path = os.path.join(output_path, "月底汇总表.csv")
    detail_txt_path = os.path.join(output_path, "月底汇总表_明细表.txt")
    detail_csv_path = os.path.join(output_path, "月底汇总表_明细表.csv")

    lines = []
    lines.append("=" * 120)
    lines.append("竣工资料组卷 - 月底汇总表")
    lines.append("=" * 120)
    lines.append(f"项目总数: {len(project_results)}")
    total_all = sum(pr['total'] for pr in project_results)
    total_organized = sum(pr['organized'] for pr in project_results)
    total_void = sum(pr['void'] for pr in project_results)
    total_unclassified = sum(pr['unclassified'] for pr in project_results)
    total_missing = sum(len(pr['missing']) for pr in project_results)
    lines.append(f"文件总计: {total_all}")
    lines.append(f"  - 已组卷: {total_organized}")
    lines.append(f"  - 作废: {total_void}")
    lines.append(f"  - 待分类: {total_unclassified}")
    lines.append(f"  - 累计缺项数: {total_missing}")
    lines.append("")

    project_results_sorted = sorted(project_results, key=lambda x: (-len(x['missing']), -x['unclassified']))

    lines.append("-" * 120)
    header = f"{'项目名称':<20}{'工程类型':<12}{'总文件':>8}{'已组卷':>8}{'作废':>6}{'待分类':>8}{'缺项数':>8}{'完成率':>8}"
    lines.append(header)
    lines.append("-" * 120)

    for pr in project_results_sorted:
        miss_cnt = len(pr['missing'])
        rate = pr['organized'] / pr['total'] * 100 if pr['total'] > 0 else 0
        lines.append(f"{pr['project_name']:<20}{pr['pt_name']:<12}{pr['total']:>8}{pr['organized']:>8}{pr['void']:>6}{pr['unclassified']:>8}{miss_cnt:>8}{rate:>7.1f}%")

    lines.append("")
    lines.append("=" * 120)
    lines.append("详细案卷分类统计:")
    lines.append("=" * 120)

    if project_results:
        all_cats = set()
        for pr in project_results:
            all_cats.update(pr['category_counts'].keys())
        all_cats = sorted(all_cats)

        cat_header = f"{'项目名称':<20}" + "".join(f"{c:>6}" for c in all_cats)
        lines.append(cat_header)
        lines.append("-" * (20 + 6 * len(all_cats)))

        for pr in project_results_sorted:
            cat_row = f"{pr['project_name']:<20}"
            for c in all_cats:
                cat_row += f"{pr['category_counts'].get(c, 0):>6}"
            lines.append(cat_row)

    lines.append("")
    lines.append("=" * 120)
    lines.append("问题项目重点关注:")
    lines.append("=" * 120)

    flag_projects = [pr for pr in project_results_sorted if len(pr['missing']) >= 3 or pr['unclassified'] >= 5]
    if not flag_projects:
        lines.append("（无严重问题项目）")
    else:
        for pr in flag_projects:
            lines.append(f"★ {pr['project_name']} ({pr['pt_name']})")
            if pr['unclassified'] >= 5:
                lines.append(f"   - 待分类文件过多: {pr['unclassified']}个，需尽快人工核对")
            if len(pr['missing']) >= 3:
                lines.append(f"   - 缺项严重: 缺少{'、'.join(pr['missing'])}")
            lines.append(f"   - 组卷完成率: {pr['organized']/pr['total']*100:.1f}%" if pr['total'] > 0 else "")
            lines.append("")

    lines.append("")
    lines.append("=" * 120)
    lines.append("附：完整明细表请查看 月底汇总表_明细表.txt / .csv")
    lines.append("=" * 120)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["项目名称", "工程类型", "总文件数", "已组卷", "作废", "待分类", "缺项数",
                         "缺项类别", "完成率(%)", "A", "B", "C", "C1", "C2", "C3", "C4", "C5",
                         "C6", "C7", "C8", "C9", "C10", "D", "E"])
        for pr in project_results:
            rate = pr['organized'] / pr['total'] * 100 if pr['total'] > 0 else 0
            cc = pr['category_counts']
            writer.writerow([
                pr['project_name'], pr['pt_name'], pr['total'], pr['organized'],
                pr['void'], pr['unclassified'], len(pr['missing']),
                "、".join(pr['missing']), f"{rate:.1f}",
                cc.get("A", 0), cc.get("B", 0), cc.get("C", 0), cc.get("C1", 0),
                cc.get("C2", 0), cc.get("C3", 0), cc.get("C4", 0), cc.get("C5", 0),
                cc.get("C6", 0), cc.get("C7", 0), cc.get("C8", 0), cc.get("C9", 0),
                cc.get("C10", 0), cc.get("D", 0), cc.get("E", 0)
            ])

    detail_lines = []
    detail_lines.append("=" * 120)
    detail_lines.append("竣工资料组卷 - 月底汇总明细表 (按项目 × 案卷类别展开)")
    detail_lines.append("=" * 120)
    detail_lines.append("")
    detail_lines.append("说明：本明细表按每个项目的每个案卷类别分别列示，方便核对单个案卷的完成情况")
    detail_lines.append("")

    all_cat_codes = ["A", "B", "C", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "D", "E"]

    detail_header = f"{'项目名称':<20}{'案卷编号':<8}{'案卷名称':<18}{'文件数':>8}{'待分类数':>10}{'作废数':>8}{'缺项标记':>10}"
    detail_lines.append(detail_header)
    detail_lines.append("-" * 120)

    for pr in project_results_sorted:
        pt_code = None
        for code, pt_obj in [("civil", "民用建筑工程"), ("industrial", "工业建筑工程"), ("municipal", "市政公用工程")]:
            if pr['pt_name'] == pt_obj:
                pt_code = code
                break
        pt = get_project_type(pt_code) if pt_code else None

        for cat_code in all_cat_codes:
            cat_name = ""
            is_missing = cat_code in pr['missing']
            file_count = pr['category_counts'].get(cat_code, 0)

            if pt:
                for vc in pt.volume_categories:
                    if vc.code == cat_code:
                        cat_name = vc.name
                        break

            if not cat_name:
                continue

            missing_mark = "✗ 缺项" if is_missing and file_count == 0 else ("(有文件)" if is_missing else "✓ 完整")
            void_count = pr['void'] if cat_code == "作废" else 0
            unclassified_count = pr['unclassified'] if cat_code == "未分类" else 0

            detail_lines.append(f"{pr['project_name']:<20}{cat_code:<8}{cat_name:<18}{file_count:>8}{unclassified_count:>10}{void_count:>8}{missing_mark:>10}")

        detail_lines.append("-" * 120)

    detail_lines.append("")
    detail_lines.append(f"合计: {len(project_results)} 个项目, {total_all} 个文件")

    with open(detail_txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(detail_lines))

    with open(detail_csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["项目名称", "工程类型", "案卷编号", "案卷名称", "文件数", "待分类数", "作废数", "是否缺项", "备注"])
        for pr in project_results_sorted:
            pt_code = None
            for code, pt_obj in [("civil", "民用建筑工程"), ("industrial", "工业建筑工程"), ("municipal", "市政公用工程")]:
                if pr['pt_name'] == pt_obj:
                    pt_code = code
                    break
            pt = get_project_type(pt_code) if pt_code else None

            for cat_code in all_cat_codes:
                cat_name = ""
                is_missing = cat_code in pr['missing']
                file_count = pr['category_counts'].get(cat_code, 0)

                if pt:
                    for vc in pt.volume_categories:
                        if vc.code == cat_code:
                            cat_name = vc.name
                            break

                if not cat_name:
                    continue

                missing_status = "是" if (is_missing and file_count == 0) else "否"
                void_count = pr['void'] if cat_code == "作废" else 0
                unclassified_count = pr['unclassified'] if cat_code == "未分类" else 0
                remark = ""
                if is_missing and file_count == 0:
                    remark = "缺项，需补充"
                elif is_missing:
                    remark = "系统判定缺项但有文件，建议人工核实"
                elif file_count > 0:
                    remark = "正常"

                writer.writerow([
                    pr['project_name'], pr['pt_name'], cat_code, cat_name,
                    file_count, unclassified_count, void_count, missing_status, remark
                ])

    return txt_path, csv_path, detail_txt_path, detail_csv_path


@dataclass
class VerifyIssue:
    level: str
    type: str
    project: str
    message: str


@dataclass
class VerifyResult:
    project_path: str
    project_name: str
    issues: List[VerifyIssue] = field(default_factory=list)
    checked_items: Dict[str, bool] = field(default_factory=dict)

    @property
    def error_count(self):
        return sum(1 for i in self.issues if i.level == "错误")

    @property
    def warning_count(self):
        return sum(1 for i in self.issues if i.level == "警告")


def parse_volume_catalog(catalog_path: str) -> Dict[str, Dict]:
    if not os.path.exists(catalog_path):
        return {}

    with open(catalog_path, 'r', encoding='utf-8') as f:
        content = f.read()

    volumes = {}
    current_vol = None

    for line in content.split('\n'):
        m = re.match(r'^卷\s*(\d+):\s*(.+?)\s*$', line)
        if m:
            vol_num = m.group(1)
            vol_dir = m.group(2).strip()
            current_vol = vol_dir
            volumes[current_vol] = {"卷号": vol_num, "文件数": None, "文件列表": []}
            continue

        if current_vol and current_vol in volumes:
            m2 = re.match(r'^\s*文件数:\s*(\d+)', line)
            if m2:
                volumes[current_vol]["文件数"] = int(m2.group(1))

    return volumes


def collect_actual_volumes(output_path: str) -> Dict[str, List[str]]:
    actual = {}
    if not os.path.isdir(output_path):
        return actual

    for item in sorted(os.listdir(output_path)):
        item_path = os.path.join(output_path, item)
        if not os.path.isdir(item_path):
            continue
        if item in ("00_作废文件", "01_待分类文件"):
            continue
        if item.startswith("00_") or item.startswith("01_"):
            continue
        files = [f for f in os.listdir(item_path)
                 if os.path.isfile(os.path.join(item_path, f)) and f != "卷内目录.txt"]
        actual[item] = sorted(files)

    return actual


def collect_actual_void_unclassified(output_path: str) -> Tuple[List[str], List[str]]:
    void_files = []
    unclassified_files = []

    void_dir = os.path.join(output_path, "00_作废文件")
    if os.path.isdir(void_dir):
        void_files = sorted([f for f in os.listdir(void_dir)
                             if os.path.isfile(os.path.join(void_dir, f))])

    unc_dir = os.path.join(output_path, "01_待分类文件")
    if os.path.isdir(unc_dir):
        unclassified_files = sorted([f for f in os.listdir(unc_dir)
                                     if os.path.isfile(os.path.join(unc_dir, f))])

    return void_files, unclassified_files


def parse_missing_report(missing_path: str) -> List[str]:
    if not os.path.exists(missing_path):
        return []

    with open(missing_path, 'r', encoding='utf-8') as f:
        content = f.read()

    missing = []
    for line in content.split('\n'):
        m = re.match(r'^\s*✗\s*(\S+)\s*-\s*(.+)', line)
        if m:
            missing.append(m.group(1))
    return missing


def verify_organized_result(project_path: str, output_path: str, project_type: str) -> Tuple[VerifyResult, str]:
    from .scanner import scan_project
    from datetime import datetime

    vr = VerifyResult(project_path=project_path, project_name=os.path.basename(project_path.rstrip(os.sep)))

    if not os.path.isdir(output_path):
        vr.issues.append(VerifyIssue("错误", "目录检查", vr.project_name, f"输出目录不存在: {output_path}"))
        return vr, ""

    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("竣工资料组卷 - 复核报告")
    report_lines.append("=" * 100)
    report_lines.append(f"项目名称: {vr.project_name}")
    report_lines.append(f"项目路径: {project_path}")
    report_lines.append(f"输出目录: {output_path}")
    report_lines.append(f"工程类型: {project_type}")
    report_lines.append(f"复核时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")

    print(f"  正在重新扫描源文件...", end="", flush=True)
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=True)
        vr.checked_items["源文件扫描"] = True
    except Exception as e:
        vr.issues.append(VerifyIssue("错误", "源文件扫描", vr.project_name, f"扫描失败: {e}"))
        report_lines.append("❌ 源文件扫描失败")
        return vr, "\n".join(report_lines)

    print(f" 核对卷内目录...", end="", flush=True)

    actual_volumes = collect_actual_volumes(output_path)
    actual_void, actual_unclassified = collect_actual_void_unclassified(output_path)
    total_organized = sum(len(v) for v in actual_volumes.values())

    catalog_path = os.path.join(output_path, "卷内目录.txt")
    catalog_volumes = parse_volume_catalog(catalog_path)

    if not os.path.exists(catalog_path):
        vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name, "卷内目录.txt 不存在"))
    else:
        vr.checked_items["卷内目录"] = True

        for vol_name, vol_info in catalog_volumes.items():
            vol_path = os.path.join(output_path, vol_name)
            if not os.path.isdir(vol_path):
                vr.issues.append(VerifyIssue("错误", "卷内目录", vr.project_name,
                                             f"目录 {vol_name} 在卷内目录中有记录，但实际文件夹不存在"))
                continue

            catalog_count = vol_info.get("文件数")
            actual_files = actual_volumes.get(vol_name, [])
            actual_count = len(actual_files)

            if catalog_count is not None and catalog_count != actual_count:
                vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name,
                                             f"案卷 {vol_name} 文件数不一致：目录记录 {catalog_count} 个，实际 {actual_count} 个"))

            vol_catalog_path = os.path.join(vol_path, "卷内目录.txt")
            if os.path.exists(vol_catalog_path):
                try:
                    with open(vol_catalog_path, 'r', encoding='utf-8') as f:
                        vol_cat_content = f.read()
                    listed_files = []
                    in_data = False
                    for line in vol_cat_content.split('\n'):
                        if '---' in line and not in_data:
                            in_data = True
                            continue
                        if not in_data:
                            continue
                        if line.startswith('本卷共') or not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) >= 2:
                            candidate = parts[1]
                            if '.' in candidate:
                                listed_files.append(candidate)

                    if len(listed_files) != actual_count:
                        vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name,
                                                     f"案卷 {vol_name} 子目录记录 {len(listed_files)} 个文件，实际 {actual_count} 个"))

                    for af in actual_files:
                        if af not in listed_files and len(listed_files) > 0:
                            vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name,
                                                         f"案卷 {vol_name} 中文件 {af} 存在于磁盘但未在卷内目录中列出"))
                except Exception:
                    pass

        for vol_name in actual_volumes:
            if vol_name not in catalog_volumes:
                vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name,
                                             f"案卷 {vol_name} 文件夹存在但未在卷内总目录中记录（文件数: {len(actual_volumes[vol_name])}）"))

    print(f" 核对缺项...", end="", flush=True)

    pt = get_project_type(project_type)
    all_categories = set()
    present_categories = set()
    expected_missing = []

    if pt:
        all_categories = {vc.code for vc in pt.volume_categories}
        for folder_name in actual_volumes.keys():
            parts = folder_name.split("_", 1)
            if parts and parts[0] in all_categories:
                present_categories.add(parts[0])
        expected_missing = sorted(all_categories - present_categories)

        missing_path = os.path.join(output_path, "缺项统计.txt")
        if os.path.exists(missing_path):
            vr.checked_items["缺项统计"] = True
            reported_missing = parse_missing_report(missing_path)
            if set(expected_missing) != set(reported_missing):
                extra = set(reported_missing) - set(expected_missing)
                missing = set(expected_missing) - set(reported_missing)
                detail = ""
                if extra:
                    detail += f" 报告多写: {sorted(extra)}"
                if missing:
                    detail += f" 报告漏写: {sorted(missing)}"
                vr.issues.append(VerifyIssue(
                    "警告", "缺项统计", vr.project_name,
                    f"缺项不一致。实际缺项: {expected_missing}, 报告缺项: {reported_missing}。{detail}"
                ))
        else:
            vr.issues.append(VerifyIssue("警告", "缺项统计", vr.project_name, "缺项统计.txt 不存在"))

    print(f" 核对重复清单...", end="", flush=True)

    dup_path = os.path.join(output_path, "重复文件清单.txt")
    if os.path.exists(dup_path):
        vr.checked_items["重复文件清单"] = True
    elif scan_result.duplicates:
        vr.issues.append(VerifyIssue(
            "警告", "重复文件清单", vr.project_name,
            f"检测到 {len(scan_result.duplicates)} 组重复文件，但重复文件清单.txt 不存在"
        ))

    checklist_path = os.path.join(output_path, "待确认文件清单.txt")
    if os.path.exists(checklist_path):
        vr.checked_items["核对清单"] = True

    report_lines.append("-" * 100)
    report_lines.append("一、源文件扫描:")
    report_lines.append(f"  文件总数: {scan_result.total_count}")
    report_lines.append(f"  已识别: {scan_result.recognized_count}")
    report_lines.append(f"  待确认: {scan_result.unrecognized_count}")
    report_lines.append(f"  重复文件: {scan_result.duplicate_count} 个 ({len(scan_result.duplicates)}组)")
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("二、案卷核对（卷内目录 vs 实际文件）:")
    report_lines.append(f"{'案卷名称':<28}{'目录记录数':>10}{'实际文件数':>10}{'状态':<10}")
    report_lines.append("-" * 60)

    for vol_name in sorted(set(list(catalog_volumes.keys()) + list(actual_volumes.keys()))):
        cat_count = catalog_volumes.get(vol_name, {}).get("文件数")
        act_count = len(actual_volumes.get(vol_name, []))

        if cat_count is None and act_count == 0:
            continue
        if vol_name not in catalog_volumes:
            status = "⚠ 目录漏记"
        elif vol_name not in actual_volumes:
            status = "❌ 文件夹缺失"
        elif cat_count == act_count:
            status = "✓ 一致"
        else:
            status = f"⚠ 不一致({cat_count}≠{act_count})"

        cat_display = str(cat_count) if cat_count is not None else "无记录"
        report_lines.append(f"  {vol_name:<26}{cat_display:>10}{act_count:>10}  {status}")

    report_lines.append("")

    void_count = len(actual_void)
    unclassified_count = len(actual_unclassified)
    report_lines.append(f"  作废文件: {void_count} 个")
    report_lines.append(f"  待分类文件: {unclassified_count} 个")
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("三、缺项核对:")
    if expected_missing:
        for m in expected_missing:
            cat_name = ""
            if pt:
                for vc in pt.volume_categories:
                    if vc.code == m:
                        cat_name = vc.name
                        break
            report_lines.append(f"  ✗ {m} - {cat_name}")
    else:
        report_lines.append("  ✓ 无缺项")
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("四、统计数字核对:")
    organized_from_folders = total_organized
    void_from_folders = void_count
    unclassified_from_folders = unclassified_count
    total_from_folders = organized_from_folders + void_from_folders + unclassified_from_folders
    report_lines.append(f"  输出目录实际文件总数: {total_from_folders}")
    report_lines.append(f"    已组卷: {organized_from_folders}")
    report_lines.append(f"    作废: {void_from_folders}")
    report_lines.append(f"    待分类: {unclassified_from_folders}")
    report_lines.append("")

    summary_path = os.path.join(output_path, "组卷汇总报告.txt")
    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary_content = f.read()
            m = re.search(r'文件总数:\s*(\d+)', summary_content)
            report_total = int(m.group(1)) if m else None
            m = re.search(r'已组卷文件:\s*(\d+)', summary_content)
            report_organized = int(m.group(1)) if m else None
            m = re.search(r'作废文件:\s*(\d+)', summary_content)
            report_void = int(m.group(1)) if m else None
            m = re.search(r'待分类文件:\s*(\d+)', summary_content)
            report_unclassified = int(m.group(1)) if m else None

            if report_total is not None and report_total != total_from_folders:
                vr.issues.append(VerifyIssue("警告", "汇总报告", vr.project_name,
                                             f"总文件数不一致：报告 {report_total}，实际 {total_from_folders}"))
            if report_organized is not None and report_organized != organized_from_folders:
                vr.issues.append(VerifyIssue("警告", "汇总报告", vr.project_name,
                                             f"已组卷数不一致：报告 {report_organized}，实际 {organized_from_folders}"))
            if report_void is not None and report_void != void_from_folders:
                vr.issues.append(VerifyIssue("警告", "汇总报告", vr.project_name,
                                             f"作废数不一致：报告 {report_void}，实际 {void_from_folders}"))
            if report_unclassified is not None and report_unclassified != unclassified_from_folders:
                vr.issues.append(VerifyIssue("警告", "汇总报告", vr.project_name,
                                             f"待分类数不一致：报告 {report_unclassified}，实际 {unclassified_from_folders}"))

            report_lines.append(f"  汇总报告记录: 总{report_total} 组卷{report_organized} 作废{report_void} 待分{report_unclassified}")
        except Exception as e:
            report_lines.append(f"  ⚠ 解析汇总报告失败: {e}")

    report_lines.append("")

    if vr.issues:
        report_lines.append("=" * 100)
        report_lines.append(f"发现问题 ({len(vr.issues)} 项):")
        report_lines.append("=" * 100)
        for idx, issue in enumerate(vr.issues, 1):
            icon = "❌" if issue.level == "错误" else "⚠️ "
            report_lines.append(f"{idx:02d}. {icon} [{issue.level}] {issue.type}: {issue.message}")
    else:
        report_lines.append("=" * 100)
        report_lines.append("✅ 所有检查项通过，未发现不一致问题")
        report_lines.append("=" * 100)

    report_path = os.path.join(output_path, "复核报告.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    return vr, report_path


def verify_batch_output(batch_output_path: str, project_type: str = None,
                        project_list_csv: str = None) -> Tuple[List[VerifyResult], str]:
    from datetime import datetime

    results = []
    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("竣工资料组卷 - 批量复核报告")
    report_lines.append("=" * 100)
    report_lines.append(f"批量输出目录: {batch_output_path}")
    report_lines.append(f"复核时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")

    project_dirs = []

    if project_list_csv and os.path.exists(project_list_csv):
        try:
            from .__main__ import parse_project_list
            projects = parse_project_list(project_list_csv)
            report_lines.append(f"使用项目清单: {project_list_csv}")
            report_lines.append(f"清单中共 {len(projects)} 个项目")
            report_lines.append("")

            for p in projects:
                if p.get('output'):
                    proj_output = os.path.abspath(p['output'])
                else:
                    proj_output = os.path.join(batch_output_path, p['name'] + "_组卷结果")

                if os.path.isdir(proj_output):
                    project_dirs.append((p['name'], p['path'], p['type'], proj_output))
                else:
                    vr = VerifyResult(project_path=p['path'], project_name=p['name'])
                    vr.issues.append(VerifyIssue("错误", "目录检查", p['name'],
                                                 f"输出目录不存在: {proj_output}"))
                    results.append(vr)
        except Exception as e:
            report_lines.append(f"⚠️  解析项目清单失败: {e}，回退到自动扫描模式")
            project_dirs = []

    if not project_dirs:
        if os.path.isdir(batch_output_path):
            for item in sorted(os.listdir(batch_output_path)):
                item_path = os.path.join(batch_output_path, item)
                if os.path.isdir(item_path) and item.endswith("_组卷结果"):
                    proj_name = item.replace("_组卷结果", "")
                    project_dirs.append((proj_name, None, None, item_path))

    if not project_dirs and not results:
        report_lines.append("未找到任何项目的组卷结果目录")
        batch_report_path = os.path.join(batch_output_path, "批量复核报告.txt")
        os.makedirs(batch_output_path, exist_ok=True)
        with open(batch_report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))
        return [], batch_report_path

    report_lines.append(f"共 {len(project_dirs)} 个项目待复核")
    report_lines.append("")

    summary_path = os.path.join(batch_output_path, "月底汇总表.csv")
    summary_data = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('项目名称', '').strip()
                    if name:
                        summary_data[name] = row
            report_lines.append(f"✓ 月底汇总表.csv 存在（{len(summary_data)} 个项目记录）")
        except Exception as e:
            report_lines.append(f"⚠️  解析月底汇总表.csv 失败: {e}")
    else:
        report_lines.append("⚠️  月底汇总表.csv 不存在")

    detail_path = os.path.join(batch_output_path, "月底汇总表_明细表.csv")
    if os.path.exists(detail_path):
        report_lines.append("✓ 月底汇总表_明细表.csv 存在")
    else:
        report_lines.append("⚠️  月底汇总表_明细表.csv 不存在")
    report_lines.append("")

    for proj_name, proj_source, proj_type, proj_output in project_dirs:
        print(f"  正在复核 [{proj_name}]...", end="", flush=True)

        detected_type = proj_type
        if not detected_type:
            checklist_path = os.path.join(proj_output, "待确认文件清单.txt")
            if os.path.exists(checklist_path):
                try:
                    with open(checklist_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    m = re.search(r'工程类型:\s*(.+?)\s*\n', content)
                    if m:
                        type_name = m.group(1).strip()
                        for code, name in [("civil", "民用建筑工程"), ("industrial", "工业建筑工程"), ("municipal", "市政公用工程")]:
                            if name == type_name:
                                detected_type = code
                                break
                except Exception:
                    pass

        if not detected_type:
            detected_type = project_type or "civil"

        actual_source = proj_source
        if not actual_source or not os.path.isdir(actual_source):
            checklist_path = os.path.join(proj_output, "待确认文件清单.txt")
            if os.path.exists(checklist_path):
                try:
                    with open(checklist_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    m = re.search(r'项目路径:\s*(.+?)\s*\n', content)
                    if m:
                        actual_source = m.group(1).strip()
                except Exception:
                    pass

        if not actual_source or not os.path.isdir(actual_source):
            vr = VerifyResult(project_path="未知", project_name=proj_name)
            vr.issues.append(VerifyIssue("错误", "项目路径", proj_name, "无法定位原始项目路径，跳过复核"))
            results.append(vr)
            print(f" ✗ 找不到源文件")
            continue

        vr, _ = verify_organized_result(actual_source, proj_output, detected_type)

        csv_row = summary_data.get(proj_name)
        if csv_row:
            actual_volumes = collect_actual_volumes(proj_output)
            actual_void, actual_unclassified = collect_actual_void_unclassified(proj_output)
            re_total = len(actual_void) + len(actual_unclassified) + sum(len(v) for v in actual_volumes.values())
            re_organized = sum(len(v) for v in actual_volumes.values())
            re_void = len(actual_void)
            re_unclassified = len(actual_unclassified)

            try:
                csv_total = int(csv_row.get('总文件数', 0))
                csv_organized = int(csv_row.get('已组卷', 0))
                csv_void = int(csv_row.get('作废', 0))
                csv_unclassified = int(csv_row.get('待分类', 0))

                if re_total != csv_total:
                    vr.issues.append(VerifyIssue("警告", "汇总表核对", proj_name,
                                                 f"总文件数不一致：CSV记录 {csv_total}，实际 {re_total}"))
                if re_organized != csv_organized:
                    vr.issues.append(VerifyIssue("警告", "汇总表核对", proj_name,
                                                 f"已组卷数不一致：CSV记录 {csv_organized}，实际 {re_organized}"))
                if re_void != csv_void:
                    vr.issues.append(VerifyIssue("警告", "汇总表核对", proj_name,
                                                 f"作废数不一致：CSV记录 {csv_void}，实际 {re_void}"))
                if re_unclassified != csv_unclassified:
                    vr.issues.append(VerifyIssue("警告", "汇总表核对", proj_name,
                                                 f"待分类数不一致：CSV记录 {csv_unclassified}，实际 {re_unclassified}"))
            except (ValueError, TypeError):
                pass

        results.append(vr)
        status = f" ✗ {vr.error_count}错{vr.warning_count}警" if (vr.error_count + vr.warning_count) > 0 else " ✓"
        print(status)

    report_lines.append("-" * 100)
    report_lines.append("项目复核结果汇总:")
    report_lines.append(f"{'项目名称':<24}{'错误':>8}{'警告':>8}{'状态':<12}")
    report_lines.append("-" * 60)

    total_errors = 0
    total_warnings = 0
    for vr in results:
        total_errors += vr.error_count
        total_warnings += vr.warning_count
        status = "⚠️  有问题" if (vr.error_count + vr.warning_count) > 0 else "✓ 正常"
        report_lines.append(f"  {vr.project_name:<22}{vr.error_count:>8}{vr.warning_count:>8}  {status:<12}")

    report_lines.append("-" * 60)
    report_lines.append(f"  {'合计':<22}{total_errors:>8}{total_warnings:>8}")
    report_lines.append("")

    csv_mismatch_projects = [vr for vr in results if any(i.type == "汇总表核对" for i in vr.issues)]
    if csv_mismatch_projects:
        report_lines.append("=" * 100)
        report_lines.append("月底汇总表数据差异:")
        report_lines.append("=" * 100)
        for vr in csv_mismatch_projects:
            csv_issues = [i for i in vr.issues if i.type == "汇总表核对"]
            report_lines.append(f"\n【{vr.project_name}】")
            for issue in csv_issues:
                icon = "❌" if issue.level == "错误" else "⚠️ "
                report_lines.append(f"  {icon} {issue.message}")

    all_issues = [i for vr in results for i in vr.issues if i.type != "汇总表核对"]
    if all_issues:
        report_lines.append("")
        report_lines.append("=" * 100)
        report_lines.append("其他问题详情:")
        report_lines.append("=" * 100)
        for vr in results:
            non_csv_issues = [i for i in vr.issues if i.type != "汇总表核对"]
            if non_csv_issues:
                report_lines.append(f"\n【{vr.project_name}】")
                for idx, issue in enumerate(non_csv_issues, 1):
                    icon = "❌" if issue.level == "错误" else "⚠️ "
                    report_lines.append(f"  {idx:02d}. {icon} [{issue.level}] {issue.type}: {issue.message}")

    if total_errors + total_warnings == 0:
        report_lines.append("")
        report_lines.append("=" * 100)
        report_lines.append("✅ 所有项目复核通过，数据一致")
        report_lines.append("=" * 100)

    batch_report_path = os.path.join(batch_output_path, "批量复核报告.txt")
    os.makedirs(batch_output_path, exist_ok=True)
    with open(batch_report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    return results, batch_report_path
