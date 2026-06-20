import argparse
import sys
import os

from . import __version__
from .config import list_project_types, get_project_type
from .scanner import scan_project, generate_checklist, generate_preliminary_list, generate_duplicate_list
from .organizer import (
    parse_checklist, merge_with_scan, organize_files,
    generate_volume_catalog, generate_missing_report, generate_summary_report
)


def cmd_scan(args):
    project_path = args.project_path
    project_type = args.project_type
    output_path = args.output
    check_duplicates = args.check_duplicates

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

    print("正在扫描文件...")
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=check_duplicates)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"扫描完成!")
    print(f"  文件总数: {scan_result.total_count}")
    print(f"  已识别: {scan_result.recognized_count}")
    print(f"  待确认: {scan_result.unrecognized_count}")

    if check_duplicates:
        print(f"  重复文件组: {len(scan_result.duplicates)}")
    print()

    print("正在生成初步分组清单...")
    preliminary_path = generate_preliminary_list(scan_result, output_path, project_type)
    print(f"  已生成: {preliminary_path}")

    print("正在生成待确认文件清单...")
    checklist_path = generate_checklist(scan_result, project_path, output_path, project_type)
    print(f"  已生成: {checklist_path}")

    if check_duplicates:
        print("正在生成重复文件清单...")
        dup_path = generate_duplicate_list(scan_result, output_path)
        print(f"  已生成: {dup_path}")

    print()
    print("=" * 60)
    print("下一步:")
    print(f"  1. 打开 '{checklist_path}'")
    print("  2. 为每个待确认文件填写【案卷类别】或标记【作废】")
    print(f"  3. 运行: python -m juanzuan organize {project_path} {output_path}")
    print("=" * 60)


def cmd_organize(args):
    project_path = args.project_path
    output_path = args.output
    project_type = args.project_type
    copy_mode = not args.move
    checklist_path = args.checklist

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
    print("竣工资料组卷工具 - 重排阶段")
    print("=" * 60)
    print(f"项目路径: {project_path}")
    print(f"工程类型: {pt.name}")
    print(f"输出位置: {output_path}")
    print(f"核对清单: {checklist_path}")
    print(f"处理模式: {'复制' if copy_mode else '移动'}")
    print()

    print("正在扫描原始文件...")
    try:
        scan_result = scan_project(project_path, project_type, calculate_hash=False)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"  共扫描到 {scan_result.total_count} 个文件")
    print()

    checked_files = []
    if os.path.exists(checklist_path):
        print("正在解析核对清单...")
        try:
            checked_files = parse_checklist(checklist_path)
            print(f"  解析到 {len(checked_files)} 个待确认文件的核对结果")
        except Exception as e:
            print(f"警告: 解析核对清单失败: {e}")
            print("将使用自动识别结果进行组卷")
    else:
        print("提示: 未找到核对清单，将使用自动识别结果进行组卷")
    print()

    print("正在合并分类结果...")
    merged_files = merge_with_scan(scan_result.files, checked_files, project_type)
    recognized = sum(1 for f in merged_files if f.category_code)
    void = sum(1 for f in merged_files if f.category_code == "作废")
    unclassified = sum(1 for f in merged_files if not f.category_code)
    print(f"  已分类: {recognized - void}")
    print(f"  作废: {void}")
    print(f"  未分类: {unclassified}")
    print()

    print("正在重排文件...")
    try:
        org_result = organize_files(project_path, output_path, merged_files, project_type, copy_mode=copy_mode)
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
    print(f"  1. 卷内总目录: {os.path.basename(catalog_path)}")
    print(f"  2. 缺项统计: {os.path.basename(missing_path)}")
    print(f"  3. 汇总报告: {os.path.basename(summary_path)}")
    print("=" * 60)


def cmd_list_types(args):
    print("=" * 60)
    print("竣工资料组卷工具 - 支持的工程类型")
    print("=" * 60)
    print()

    for pt in list_project_types():
        print(f"[{pt.code}] {pt.name}")
        print(f"  案卷类别:")
        for vc in pt.volume_categories:
            print(f"    {vc.code} - {vc.name}")
        print()


def main():
    parser = argparse.ArgumentParser(
        prog="juanzuan",
        description="竣工资料组卷批处理命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  扫描项目文件，生成待确认清单:
    python -m juanzuan scan D:\\项目A civil D:\\输出

  根据核对结果重排文件:
    python -m juanzuan organize D:\\项目A D:\\输出 --project-type civil

  查看支持的工程类型:
    python -m juanzuan list-types
        """
    )

    parser.add_argument("--version", action="version", version=f"juanzuan {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    scan_parser = subparsers.add_parser("scan", help="扫描文件，生成初步分组清单和待确认列表")
    scan_parser.add_argument("project_path", help="项目文件夹路径")
    scan_parser.add_argument("project_type", help="工程类型 (如: civil, industrial, municipal)")
    scan_parser.add_argument("output", help="输出位置路径")
    scan_parser.add_argument("--check-duplicates", action="store_true", help="检测重复文件（较慢）")
    scan_parser.set_defaults(func=cmd_scan)

    organize_parser = subparsers.add_parser("organize", help="根据核对结果重排文件")
    organize_parser.add_argument("project_path", help="项目文件夹路径")
    organize_parser.add_argument("output", help="输出位置路径（扫描阶段的输出目录）")
    organize_parser.add_argument("--project-type", default="civil", help="工程类型 (默认: civil)")
    organize_parser.add_argument("--checklist", help="指定核对清单路径 (默认: 输出目录/待确认文件清单.txt)")
    organize_parser.add_argument("--move", action="store_true", help="移动文件而非复制 (默认: 复制)")
    organize_parser.set_defaults(func=cmd_organize)

    list_parser = subparsers.add_parser("list-types", help="列出支持的工程类型和案卷类别")
    list_parser.set_defaults(func=cmd_list_types)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
