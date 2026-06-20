import os
import shutil


def write_file(filepath, content):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def create_project_锦园(base_dir):
    name = "01_锦园住宅小区"
    root = os.path.join(base_dir, name)
    if os.path.exists(root):
        shutil.rmtree(root)

    files = [
        ("1号楼资料", "1号楼-施工组织设计-20240301-001.pdf", "A类文件"),
        ("1号楼资料", "1号楼-隐蔽记录-001.pdf", "C4类文件"),
        ("1号楼资料", "1号楼-隐蔽记录-002.pdf", "C4类文件"),
        ("1号楼资料", "1号楼-检验批-20240315-003.pdf", "C6类文件"),
        ("1号楼资料", "1号楼-竣工图-建施01.pdf", "D类文件"),
        ("1号楼资料", "1号楼-竣工图-结施01.pdf", "D类文件"),
        ("2号楼资料", "2号楼-施工组织设计-20240305-001.pdf", "A类文件"),
        ("2号楼资料", "2号楼-隐蔽工程-001.pdf", "C4类文件"),
        ("2号楼资料", "2号楼-检验批-001.pdf", "C6类文件"),
        ("2号楼资料", "2号楼-监理通知单-20240410.pdf", "B类文件"),
        ("公共部分", "立项批复文件-20240101.pdf", "A类文件"),
        ("公共部分", "土地使用证.pdf", "A类文件"),
        ("公共部分", "规划许可证.pdf", "A类文件"),
        ("公共部分", "工程照片-20240301.jpg", "E类文件"),
        ("公共部分", "工程照片-20240401.jpg", "E类文件"),
        ("公共部分", "监理例会纪要-20240310.pdf", "B类文件"),
        ("公共部分", "监理例会纪要-20240317.pdf", "B类文件"),
        ("地下室", "地下室-防水验收-001.pdf", "C7类文件"),
        ("地下室", "地下室-隐蔽记录-001.pdf", "C4类文件"),
        ("扫描件", "scan_20240320_001.pdf", "未分类扫描件"),
        ("扫描件", "scan_20240320_002.pdf", "未分类扫描件"),
        ("扫描件", "unknown_file.pdf", "未分类"),
        ("扫描件", "IMG_0001.jpg", "未分类照片"),
        ("扫描件", "IMG_0002.jpg", "未分类照片"),
    ]

    for subdir, fname, content in files:
        write_file(os.path.join(root, subdir, fname), f"{content}\n{fname}")

    return name


def create_project_科技园(base_dir):
    name = "02_科技园厂房"
    root = os.path.join(base_dir, name)
    if os.path.exists(root):
        shutil.rmtree(root)

    files = [
        ("1号厂房", "1号厂房-施工组织-001.pdf", "施工组织"),
        ("1号厂房", "1号厂房-隐蔽记录-001.pdf", "隐蔽1"),
        ("1号厂房", "1号厂房-隐蔽记录-002.pdf", "隐蔽2"),
        ("1号厂房", "1号厂房-材料进场-001.pdf", "材料"),
        ("1号厂房", "1号厂房-工艺设备调试-001.pdf", "工艺设备"),
        ("1号厂房", "1号厂房-工艺设备调试-002.pdf", "工艺设备"),
        ("1号厂房", "1号厂房-竣工图-工艺01.pdf", "竣工图"),
        ("2号厂房", "2号厂房-施工日志-03月.pdf", "C1类"),
        ("2号厂房", "2号厂房-施工日志-04月.pdf", "C1类"),
        ("2号厂房", "2号厂房-试验报告-混凝土.pdf", "C5类"),
        ("2号厂房", "2号厂房-试验报告-钢筋.pdf", "C5类"),
        ("2号厂房", "2号厂房-管道安装记录-001.pdf", "C9类"),
        ("2号厂房", "2号厂房-管道安装记录-002.pdf", "C9类"),
        ("综合办公", "办公楼-开工报告.pdf", "A类"),
        ("综合办公", "办公楼-合同文件.pdf", "A类"),
        ("综合办公", "办公楼-设计变更-001.pdf", "C2类"),
        ("综合办公", "办公楼-设计变更-002.pdf", "C2类"),
        ("综合办公", "办公楼-工程洽商-编号005.pdf", "C类"),
        ("监理资料", "监理规划.pdf", "B类"),
        ("监理资料", "监理实施细则.pdf", "B类"),
        ("监理资料", "旁站记录-001.pdf", "B类"),
        ("监理资料", "监理通知单-质量整改.pdf", "B类"),
        ("声像资料", "现场照片-001.jpg", "E类"),
        ("声像资料", "现场照片-002.jpg", "E类"),
        ("声像资料", "现场照片-003.jpg", "E类"),
        ("声像资料", "视频-基础浇筑.mp4", "E类"),
    ]

    for subdir, fname, content in files:
        write_file(os.path.join(root, subdir, fname), f"{content}\n{fname}")

    return name


def create_project_市政路(base_dir):
    name = "03_城北大道市政工程"
    root = os.path.join(base_dir, name)
    if os.path.exists(root):
        shutil.rmtree(root)

    files = [
        ("道路工程", "路基-检验批-001.pdf", "C8类"),
        ("道路工程", "路基-检验批-002.pdf", "C8类"),
        ("道路工程", "路面-隐蔽记录-001.pdf", "C8类"),
        ("道路工程", "路面-材料进场-沥青.pdf", "C3类"),
        ("道路工程", "道路-竣工图-平纵断面.pdf", "D类"),
        ("桥梁工程", "桥梁-桩基施工记录-001.pdf", "C9类"),
        ("桥梁工程", "桥梁-桩基施工记录-002.pdf", "C9类"),
        ("桥梁工程", "桥梁-桥台验收.pdf", "C9类"),
        ("桥梁工程", "桥梁-试验报告-桩基.pdf", "C5类"),
        ("给排水", "给水-管道安装-001.pdf", "C10类"),
        ("给排水", "给水-管道安装-002.pdf", "C10类"),
        ("给排水", "排水-井室砌筑-001.pdf", "C10类"),
        ("给排水", "排水-闭水试验-001.pdf", "C5类"),
        ("前期资料", "立项-可研报告.pdf", "A类"),
        ("前期资料", "规划-选址意见.pdf", "A类"),
        ("前期资料", "土地-用地预审.pdf", "A类"),
        ("前期资料", "招标-招标文件.pdf", "A类"),
        ("前期资料", "合同-施工合同.pdf", "A类"),
        ("竣工文件", "竣工验收报告.pdf", "C7类"),
        ("竣工文件", "竣工总结.pdf", "C7类"),
        ("竣工文件", "交工证书.pdf", "C7类"),
    ]

    for subdir, fname, content in files:
        write_file(os.path.join(root, subdir, fname), f"{content}\n{fname}")

    return name


def create_batch_projects(base_dir):
    batch_root = os.path.join(base_dir, "月底批量项目_2026年06月")
    if os.path.exists(batch_root):
        shutil.rmtree(batch_root)

    os.makedirs(batch_root, exist_ok=True)

    p1 = create_project_锦园(batch_root)
    p2 = create_project_科技园(batch_root)
    p3 = create_project_市政路(batch_root)

    print(f"批量测试数据已创建: {batch_root}")
    print(f"包含项目: {p1}, {p2}, {p3}")
    return batch_root


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    create_batch_projects(base)
