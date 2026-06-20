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


def verify_organized_result(project_path: str, output_path: str, project_type: str) -> Tuple[VerifyResult, str]:
    """
    复核已组卷的结果：核对卷内目录、缺项统计、重复文件清单的一致性
    """
    from .scanner import scan_project

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
    report_lines.append(f"复核时间: {os.popen('date /t').read().strip()} {os.popen('time /t').read().strip()}")
    report_lines.append("")

    print(f"  正在重新扫描源文件...", end="", flush=True)
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=True)
        vr.checked_items["源文件扫描"] = True
    except Exception as e:
        vr.issues.append(VerifyIssue("错误", "源文件扫描", vr.project_name, f"扫描失败: {e}"))
        report_lines.append("❌ 源文件扫描失败")
        return vr, "\n".join(report_lines)

    print(f" 检查卷内目录...", end="", flush=True)

    catalog_path = os.path.join(output_path, "卷内目录.txt")
    expected_volumes = set()
    actual_volume_files = defaultdict(list)

    if os.path.isdir(output_path):
        for item in os.listdir(output_path):
            item_path = os.path.join(output_path, item)
            if os.path.isdir(item_path) and not item.startswith("00_") and not item.startswith("01_"):
                volume_files = [f for f in os.listdir(item_path)
                                if os.path.isfile(os.path.join(item_path, f)) and f != "卷内目录.txt"]
                actual_volume_files[item] = volume_files

    total_organized = sum(len(v) for v in actual_volume_files.values())

    if not os.path.exists(catalog_path):
        vr.issues.append(VerifyIssue("警告", "卷内目录", vr.project_name, "卷内目录.txt 不存在"))
    else:
        vr.checked_items["卷内目录"] = True

    pt = get_project_type(project_type)
    if pt:
        all_categories = {vc.code for vc in pt.volume_categories}
        expected_missing = set()
        present_categories = set()

        for folder_name in actual_volume_files.keys():
            parts = folder_name.split("_", 1)
            if parts:
                cat_code = parts[0]
                if cat_code in all_categories:
                    present_categories.add(cat_code)

        expected_missing = sorted(all_categories - present_categories)

        missing_path = os.path.join(output_path, "缺项统计.txt")
        if os.path.exists(missing_path):
            vr.checked_items["缺项统计"] = True
            try:
                with open(missing_path, 'r', encoding='utf-8') as f:
                    missing_content = f.read()
                reported_missing = []
                for cat in all_categories:
                    if f"✗ {cat}" in missing_content or f"{cat} -" in missing_content:
                        has_files = False
                        for folder_name in actual_volume_files.keys():
                            if folder_name.startswith(cat + "_"):
                                has_files = True
                                break
                        if not has_files:
                            reported_missing.append(cat)

                if set(expected_missing) != set(reported_missing):
                    vr.issues.append(VerifyIssue(
                        "警告", "缺项统计", vr.project_name,
                        f"缺项不一致。实际缺项: {expected_missing}, 报告缺项: {reported_missing}"
                    ))
            except Exception as e:
                vr.issues.append(VerifyIssue("警告", "缺项统计", vr.project_name, f"解析缺项统计失败: {e}"))

    dup_path = os.path.join(output_path, "重复文件清单.txt")
    if os.path.exists(dup_path):
        vr.checked_items["重复文件清单"] = True
        if scan_result.duplicates:
            try:
                with open(dup_path, 'r', encoding='utf-8') as f:
                    dup_content = f.read()
                if f"重复文件组数: {len(scan_result.duplicates)}" not in dup_content:
                    vr.issues.append(VerifyIssue(
                        "警告", "重复文件清单", vr.project_name,
                        f"重复文件组数不一致。实际: {len(scan_result.duplicates)}组, 报告中可能有误"
                    ))
            except Exception as e:
                vr.issues.append(VerifyIssue("警告", "重复文件清单", vr.project_name, f"解析失败: {e}"))
    elif scan_result.duplicates:
        vr.issues.append(VerifyIssue(
            "警告", "重复文件清单", vr.project_name,
            f"检测到 {len(scan_result.duplicates)} 组重复文件，但重复文件清单.txt 不存在"
        ))

    checklist_path = os.path.join(output_path, "待确认文件清单.txt")
    if os.path.exists(checklist_path):
        vr.checked_items["核对清单"] = True

    report_lines.append("-" * 100)
    report_lines.append("复核内容:")
    report_lines.append(f"  ✓ 源文件扫描: {scan_result.total_count} 个文件")
    report_lines.append(f"  ✓ 检测到重复: {scan_result.duplicate_count} 个文件 ({len(scan_result.duplicates)}组)")
    report_lines.append(f"  ✓ 已组卷文件: {total_organized} 个 (在 {len(actual_volume_files)} 个案卷中)")
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("案卷核对:")
    report_lines.append(f"{'案卷':<24}{'文件数':>10}{'状态':<10}")
    report_lines.append("-" * 50)
    for vol_name, files in sorted(actual_volume_files.items()):
        report_lines.append(f"  {vol_name:<22}{len(files):>10}  ✓ 正常")
    report_lines.append("")

    if expected_missing:
        report_lines.append(f"缺项类别 ({len(expected_missing)}个):")
        for m in expected_missing:
            cat_name = ""
            if pt:
                for vc in pt.volume_categories:
                    if vc.code == m:
                        cat_name = vc.name
                        break
            report_lines.append(f"  ✗ {m} - {cat_name}")
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


def verify_batch_output(batch_output_path: str, project_type: str = None) -> Tuple[List[VerifyResult], str]:
    """
    复核批量输出目录下的所有项目
    """
    results = []
    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("竣工资料组卷 - 批量复核报告")
    report_lines.append("=" * 100)
    report_lines.append(f"批量输出目录: {batch_output_path}")
    report_lines.append(f"复核时间: {os.popen('date /t').read().strip()} {os.popen('time /t').read().strip()}")
    report_lines.append("")

    project_dirs = []
    if os.path.isdir(batch_output_path):
        for item in sorted(os.listdir(batch_output_path)):
            item_path = os.path.join(batch_output_path, item)
            if os.path.isdir(item_path) and item.endswith("_组卷结果"):
                project_dirs.append(item_path)

    if not project_dirs:
        report_lines.append("未找到任何项目的组卷结果目录")
        return [], "\n".join(report_lines)

    report_lines.append(f"发现 {len(project_dirs)} 个项目的组卷结果")
    report_lines.append("")

    summary_path = os.path.join(batch_output_path, "月底汇总表.csv")
    if os.path.exists(summary_path):
        report_lines.append("✓ 月底汇总表.csv 存在")
    else:
        report_lines.append("⚠️  月底汇总表.csv 不存在")

    detail_path = os.path.join(batch_output_path, "月底汇总表_明细表.csv")
    if os.path.exists(detail_path):
        report_lines.append("✓ 月底汇总表_明细表.csv 存在")
    else:
        report_lines.append("⚠️  月底汇总表_明细表.csv 不存在")
    report_lines.append("")

    for proj_output in project_dirs:
        proj_name = os.path.basename(proj_output).replace("_组卷结果", "")
        print(f"  正在复核 [{proj_name}]...", end="", flush=True)

        proj_source = None
        checklist_path = os.path.join(proj_output, "待确认文件清单.txt")
        detected_type = project_type
        if os.path.exists(checklist_path):
            try:
                with open(checklist_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                m = re.search(r'项目路径:\s*(.+?)\s*\n', content)
                if m:
                    proj_source = m.group(1).strip()
                m = re.search(r'工程类型:\s*(.+?)\s*\n', content)
                if m:
                    type_name = m.group(1).strip()
                    for code, name in [("civil", "民用建筑工程"), ("industrial", "工业建筑工程"), ("municipal", "市政公用工程")]:
                        if name == type_name:
                            detected_type = code
                            break
            except Exception:
                pass

        if not proj_source or not os.path.isdir(proj_source):
            for possible_name in [proj_name, proj_name.replace("01_", "").replace("02_", "").replace("03_", "")]:
                for base_dir in [os.path.dirname(batch_output_path)]:
                    test_path = os.path.join(base_dir, possible_name)
                    if os.path.isdir(test_path):
                        proj_source = test_path
                        break

        if not proj_source or not os.path.isdir(proj_source):
            vr = VerifyResult(project_path="未知", project_name=proj_name)
            vr.issues.append(VerifyIssue("错误", "项目路径", proj_name, "无法定位原始项目路径，跳过复核"))
            results.append(vr)
            print(f" ✗ 找不到源文件")
            continue

        vr, _ = verify_organized_result(proj_source, proj_output, detected_type or "civil")
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

    if total_errors + total_warnings > 0:
        report_lines.append("=" * 100)
        report_lines.append("问题详情:")
        report_lines.append("=" * 100)
        for vr in results:
            if vr.issues:
                report_lines.append(f"\n【{vr.project_name}】")
                for idx, issue in enumerate(vr.issues, 1):
                    icon = "❌" if issue.level == "错误" else "⚠️ "
                    report_lines.append(f"  {idx:02d}. {icon} [{issue.level}] {issue.type}: {issue.message}")

    batch_report_path = os.path.join(batch_output_path, "批量复核报告.txt")
    with open(batch_report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    return results, batch_report_path
