import argparse
import sys
import os

from . import __version__
from .config import list_project_types, get_project_type
from .scanner import scan_project, generate_checklist, generate_preliminary_list, generate_duplicate_list
from .organizer import (
    parse_checklist, merge_with_scan, build_action_plan, execute_actions,
    print_preview, generate_volume_catalog, generate_missing_report,
    generate_summary_report, generate_monthly_summary
)


def cmd_scan(args):
    project_path = args.project_path
    project_type = args.project_type
    output_path = args.output

    if not os.path.isabs(project_path):
        project_path = os.path.abspath(project_path)

    if not os.path.isabs(output_path):
        output_path = os.path.abspath(output_path)

    pt = get_project_type(project_type)
    if not pt:
        print(f"错误: 不支持的工程类型 '{project_type}'")
        print("可用的工程类型:")
        for pt_item in list_project_types():
            print(f"  {pt_item.code} - {pt_item.name}")
        sys.exit(1)

    print("=" * 60)
    print("竣工资料组卷工具 - 扫描阶段")
    print("=" * 60)
    print(f"项目路径: {project_path}")
    print(f"工程类型: {pt.name}")
    print(f"输出位置: {output_path}")
    print()

    print("正在扫描文件（默认检测重复文件）...")
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=True)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"扫描完成!")
    print(f"  文件总数: {scan_result.total_count}")
    print(f"  已识别: {scan_result.recognized_count}")
    print(f"  待确认: {scan_result.unrecognized_count}")
    print(f"  重复文件: {scan_result.duplicate_count} 个 ({len(scan_result.duplicates)}组)")
    print()

    print("正在生成初步分组清单...")
    preliminary_path = generate_preliminary_list(scan_result, output_path, project_type)
    print(f"  已生成: {preliminary_path}")

    print("正在生成待确认文件清单...")
    checklist_path = generate_checklist(scan_result, project_path, output_path, project_type)
    print(f"  已生成: {checklist_path}")

    print("正在生成重复文件清单...")
    dup_path = generate_duplicate_list(scan_result, output_path)
    print(f"  已生成: {dup_path}")

    print()
    print("=" * 60)
    print("下一步:")
    print(f"  1. 打开 '{checklist_path}'")
    print("     - 在【批量归类规则】区块添加规则（可选）")
    print("     - 为每个待确认文件填写【案卷类别】或标记【作废】")
    print(f"  2. 预览处理计划: python juanzuan_tool.py organize {project_path} {output_path} --preview")
    print(f"  3. 正式执行:   python juanzuan_tool.py organize {project_path} {output_path}")
    print("=" * 60)


def cmd_organize(args):
    project_path = args.project_path
    output_path = args.output
    project_type = args.project_type
    copy_mode = not args.move
    checklist_path = args.checklist
    preview_mode = args.preview
    yes = args.yes

    if not os.path.isabs(project_path):
        project_path = os.path.abspath(project_path)

    if not os.path.isabs(output_path):
        output_path = os.path.abspath(output_path)

    pt = get_project_type(project_type)
    if not pt:
        print(f"错误: 不支持的工程类型 '{project_type}'")
        print("可用的工程类型:")
        for pt_item in list_project_types():
            print(f"  {pt_item.code} - {pt_item.name}")
        sys.exit(1)

    if not checklist_path:
        checklist_path = os.path.join(output_path, "待确认文件清单.txt")

    if not os.path.isabs(checklist_path):
        checklist_path = os.path.abspath(checklist_path)

    print("=" * 60)
    print("竣工资料组卷工具 - 重排阶段", "(预览模式)" if preview_mode else "")
    print("=" * 60)
    print(f"项目路径: {project_path}")
    print(f"工程类型: {pt.name}")
    print(f"输出位置: {output_path}")
    print(f"核对清单: {checklist_path}")
    print(f"处理模式: {'复制' if copy_mode else '移动'}")
    print()

    print("正在扫描原始文件...")
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=True)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"  共扫描到 {scan_result.total_count} 个文件")
    print()

    checked_files = []
    batch_rules = []
    if os.path.exists(checklist_path):
        print("正在解析核对清单...")
        try:
            checked_files, batch_rules = parse_checklist(checklist_path)
            print(f"  解析到 {len(checked_files)} 个待确认文件的核对结果")
            if batch_rules:
                print(f"  解析到 {len(batch_rules)} 条批量归类规则:")
                for r in batch_rules:
                    print(f"    - {r.rule_type}|{r.rule_content}|{r.category_code}  ({r.remark})")
        except Exception as e:
            print(f"警告: 解析核对清单失败: {e}")
            print("将使用自动识别结果进行组卷")
    else:
        print("提示: 未找到核对清单，将使用自动识别结果进行组卷")
    print()

    print("正在合并分类结果...")
    merged_files = merge_with_scan(scan_result.files, checked_files, batch_rules, project_type)
    recognized = sum(1 for f in merged_files if f.category_code and f.category_code != "作废")
    void = sum(1 for f in merged_files if f.category_code == "作废")
    unclassified = sum(1 for f in merged_files if not f.category_code)
    print(f"  已分类: {recognized}")
    print(f"  作废: {void}")
    print(f"  未分类: {unclassified}")
    print()

    print("正在构建处理计划...")
    org_result, _ = build_action_plan(project_path, output_path, merged_files, project_type)
    print(f"  共 {len(org_result.actions)} 个处理动作")
    print()

    if preview_mode:
        print_preview(org_result)
        print()
        print("【预览完成】如无问题，去掉 --preview 参数即可正式执行")
        return

    if not yes:
        confirm = input(f"确认开始处理 {org_result.total_files} 个文件? (Y/n): ").strip()
        if confirm and confirm.lower() != 'y':
            print("已取消操作")
            return

    print("正在执行文件处理...")
    try:
        execute_actions(project_path, output_path, org_result, copy_mode=copy_mode)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"  处理文件总数: {org_result.total_files}")
    print(f"  已组卷: {org_result.organized_files}")
    print(f"  作废: {org_result.void_files}")
    print(f"  待分类: {org_result.skipped_files}")
    if org_result.errors:
        print(f"  错误数: {len(org_result.errors)}")
    print()

    print("正在生成重复文件清单...")
    dup_path = generate_duplicate_list(scan_result, output_path)
    print(f"  已生成: {dup_path}")

    print("正在生成卷内目录...")
    catalog_path = generate_volume_catalog(output_path, project_type)
    print(f"  已生成: {catalog_path}")

    print("正在生成缺项统计...")
    missing_path = generate_missing_report(output_path, project_type, org_result.missing_categories)
    print(f"  已生成: {missing_path}")

    print("正在生成汇总报告...")
    summary_path = generate_summary_report(output_path, org_result, project_type)
    print(f"  已生成: {summary_path}")

    print()
    print("=" * 60)
    print("组卷完成!")
    print(f"输出目录: {output_path}")
    print()
    print("生成的文件:")
    print(f"  1. 重复文件清单: {os.path.basename(dup_path)}")
    print(f"  2. 卷内总目录: {os.path.basename(catalog_path)}")
    print(f"  3. 缺项统计: {os.path.basename(missing_path)}")
    print(f"  4. 汇总报告: {os.path.basename(summary_path)}")
    print("=" * 60)


def cmd_list_types(args):
    print("=" * 60)
    print("竣工资料组卷工具 - 支持的工程类型")
    print("=" * 60)
    print()

    for pt in list_project_types():
        print(f"[{pt.code}] {pt.name}  ({len(pt.volume_categories)} 个案卷类别)")
        print(f"  案卷类别:")
        for vc in pt.volume_categories:
            print(f"    {vc.code:<4} - {vc.name}")
        print()


def process_single_project(project_dir, project_name, project_type_code, parent_output, copy_mode):
    project_path = os.path.abspath(project_dir)
    project_output = os.path.join(parent_output, project_name + "_组卷结果")

    pt = get_project_type(project_type_code)
    if not pt:
        return {
            "project_name": project_name,
            "error": f"不支持的工程类型: {project_type_code}",
            "total": 0, "organized": 0, "void": 0, "unclassified": 0,
            "missing": [], "category_counts": {}, "pt_name": project_type_code
        }

    print(f"  [{project_name}] 扫描中...", end="", flush=True)
    try:
        scan_result = scan_project(project_path, project_type_code, calculate_hash=True)
    except Exception as e:
        print(f" 失败: {e}")
        return {
            "project_name": project_name,
            "error": f"扫描失败: {e}",
            "total": 0, "organized": 0, "void": 0, "unclassified": 0,
            "missing": [], "category_counts": {}, "pt_name": pt.name
        }

    checklist_path = os.path.join(project_output, "待确认文件清单.txt")
    checked_files = []
    batch_rules = []
    if os.path.exists(checklist_path):
        try:
            checked_files, batch_rules = parse_checklist(checklist_path)
        except Exception:
            pass

    merged_files = merge_with_scan(scan_result.files, checked_files, batch_rules, project_type_code)

    print(f" 构建计划...", end="", flush=True)
    os.makedirs(project_output, exist_ok=True)
    generate_preliminary_list(scan_result, project_output, project_type_code)
    generate_checklist(scan_result, project_path, project_output, project_type_code)
    generate_duplicate_list(scan_result, project_output)

    org_result, _ = build_action_plan(project_path, project_output, merged_files, project_type_code)
    print(f" 执行处理...", end="", flush=True)
    execute_actions(project_path, project_output, org_result, copy_mode=copy_mode)

    generate_volume_catalog(project_output, project_type_code)
    generate_missing_report(project_output, project_type_code, org_result.missing_categories)
    generate_summary_report(project_output, org_result, project_type_code)

    result_dict = {
        "project_name": project_name,
        "pt_name": pt.name,
        "total": org_result.total_files,
        "organized": org_result.organized_files,
        "void": org_result.void_files,
        "unclassified": org_result.skipped_files,
        "missing": org_result.missing_categories,
        "category_counts": dict(org_result.category_counts),
        "error": None
    }

    status = f"{org_result.total_files}文件, {len(org_result.missing_categories)}缺项"
    if org_result.skipped_files > 0:
        status += f", {org_result.skipped_files}待分类"
    print(f" ✓ {status}")
    return result_dict


def cmd_batch(args):
    batch_dir = args.batch_dir
    project_type = args.project_type
    output_path = args.output
    copy_mode = not args.move
    preview = args.preview

    if not os.path.isabs(batch_dir):
        batch_dir = os.path.abspath(batch_dir)

    if not os.path.isabs(output_path):
        output_path = os.path.abspath(output_path)

    pt = get_project_type(project_type)
    if not pt:
        print(f"错误: 不支持的工程类型 '{project_type}'")
        sys.exit(1)

    print("=" * 60)
    print("竣工资料组卷工具 - 批量项目模式")
    print("=" * 60)
    print(f"批量目录: {batch_dir}")
    print(f"工程类型: {pt.name}")
    print(f"输出位置: {output_path}")
    print(f"处理模式: {'复制' if copy_mode else '移动'}")
    print(f"运行方式: {'预览' if preview else '正式执行'}")
    print()

    if not os.path.isdir(batch_dir):
        print(f"错误: 批量目录不存在: {batch_dir}")
        sys.exit(1)

    project_dirs = []
    for item in sorted(os.listdir(batch_dir)):
        item_path = os.path.join(batch_dir, item)
        if os.path.isdir(item_path):
            has_files = any(
                os.path.isfile(os.path.join(root, f))
                for root, dirs, files in os.walk(item_path)
                for f in files
            )
            if has_files:
                project_dirs.append((item, item_path))

    if not project_dirs:
        print("错误: 未找到任何包含文件的项目子目录")
        sys.exit(1)

    print(f"发现 {len(project_dirs)} 个项目目录:")
    for name, _ in project_dirs:
        file_count = sum(
            len([f for f in files if os.path.isfile(os.path.join(root, f))])
            for root, dirs, files in os.walk(os.path.join(batch_dir, name))
        )
        print(f"  - {name}  ({file_count} 个文件)")
    print()

    if preview:
        print("【预览模式】以下是批量处理计划（未实际执行）:")
        print()
        for name, path in project_dirs:
            try:
                sr = scan_project(path, project_type, calculate_hash=False)
                miss_rate_info = ""
                if sr.unrecognized_count > 5:
                    miss_rate_info = f" ⚠待确认较多"
                print(f"  {name}: {sr.total_count}文件, {sr.unrecognized_count}待确认{miss_rate_info}")
            except Exception as e:
                print(f"  {name}: 扫描失败 - {e}")
        print()
        print("如确认无误，去掉 --preview 参数即可正式执行批量处理")
        return

    print("开始批量处理...")
    print("-" * 60)

    all_results = []
    for name, path in project_dirs:
        try:
            r = process_single_project(path, name, project_type, output_path, copy_mode)
        except Exception as e:
            print(f"  [{name}] ✗ 处理异常: {e}")
            r = {
                "project_name": name,
                "pt_name": pt.name,
                "total": 0, "organized": 0, "void": 0, "unclassified": 0,
                "missing": [], "category_counts": {}, "error": str(e)
            }
        all_results.append(r)

    print("-" * 60)
    print()

    print("正在生成月底汇总表...")
    os.makedirs(output_path, exist_ok=True)
    txt_path, csv_path = generate_monthly_summary(all_results, output_path)
    print(f"  TXT 汇总表: {txt_path}")
    print(f"  CSV 汇总表: {csv_path}")
    print()

    ok_count = sum(1 for r in all_results if not r.get('error'))
    err_count = len(all_results) - ok_count
    total_files = sum(r['total'] for r in all_results)
    total_missing = sum(len(r['missing']) for r in all_results)

    print("=" * 60)
    print("批量处理完成!")
    print(f"  项目总数: {len(all_results)}  (成功: {ok_count}, 异常: {err_count})")
    print(f"  文件总数: {total_files}")
    print(f"  累计缺项: {total_missing} 项")
    print(f"  输出目录: {output_path}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        prog="juanzuan",
        description="竣工资料组卷批处理命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
单项目流程:
  1. 扫描:  python juanzuan_tool.py scan <项目路径> <civil|industrial|municipal> <输出>
  2. 核对:  打开输出目录/待确认文件清单.txt 填写类别
  3. 预览:  python juanzuan_tool.py organize <项目路径> <输出> --preview
  4. 执行:  python juanzuan_tool.py organize <项目路径> <输出>

批量流程:
  1. 预览:  python juanzuan_tool.py batch <批量目录> <工程类型> <汇总输出> --preview
  2. 执行:  python juanzuan_tool.py batch <批量目录> <工程类型> <汇总输出>

查看支持类型:
  python juanzuan_tool.py list-types
        """
    )

    parser.add_argument("--version", action="version", version=f"juanzuan {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    scan_parser = subparsers.add_parser("scan", help="扫描文件，生成初步分组清单和待确认列表（默认检测重复）")
    scan_parser.add_argument("project_path", help="项目文件夹路径")
    scan_parser.add_argument("project_type", help="工程类型: civil/industrial/municipal")
    scan_parser.add_argument("output", help="输出位置路径")
    scan_parser.set_defaults(func=cmd_scan)

    organize_parser = subparsers.add_parser("organize", help="根据核对结果重排文件")
    organize_parser.add_argument("project_path", help="项目文件夹路径")
    organize_parser.add_argument("output", help="输出位置路径（扫描阶段的输出目录）")
    organize_parser.add_argument("--project-type", default="civil", help="工程类型 (默认: civil)")
    organize_parser.add_argument("--checklist", help="指定核对清单路径（默认: 输出目录/待确认文件清单.txt）")
    organize_parser.add_argument("--move", action="store_true", help="移动文件而非复制 (默认: 复制)")
    organize_parser.add_argument("--preview", action="store_true", help="预览模式，只显示处理计划不实际执行")
    organize_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示，直接执行")
    organize_parser.set_defaults(func=cmd_organize)

    list_parser = subparsers.add_parser("list-types", help="列出支持的工程类型和案卷类别")
    list_parser.set_defaults(func=cmd_list_types)

    batch_parser = subparsers.add_parser("batch", help="批量项目模式：自动处理多个项目目录，生成月底汇总")
    batch_parser.add_argument("batch_dir", help="包含多个项目子文件夹的目录")
    batch_parser.add_argument("project_type", help="工程类型: civil/industrial/municipal")
    batch_parser.add_argument("output", help="汇总输出位置路径")
    batch_parser.add_argument("--move", action="store_true", help="移动文件而非复制 (默认: 复制)")
    batch_parser.add_argument("--preview", action="store_true", help="预览模式，只显示概况不实际执行")
    batch_parser.set_defaults(func=cmd_batch)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
