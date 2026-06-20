import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class VolumeCategory:
    code: str
    name: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class ProjectType:
    code: str
    name: str
    volume_categories: List[VolumeCategory]


PROJECT_TYPES: Dict[str, ProjectType] = {
    "civil": ProjectType(
        code="civil",
        name="民用建筑工程",
        volume_categories=[
            VolumeCategory("A", "工程准备阶段文件", ["立项", "可研", "规划", "土地", "勘察", "设计", "招标", "合同", "开工"]),
            VolumeCategory("B", "监理文件", ["监理", "旁站", "巡视", "平行检验", "监理规划", "监理实施细则"]),
            VolumeCategory("C", "施工文件", ["施工", "技术交底", "图纸会审", "设计变更", "工程洽商"]),
            VolumeCategory("C1", "施工管理文件", ["施工组织", "施工日志", "现场管理", "项目部"]),
            VolumeCategory("C2", "施工技术文件", ["技术交底", "图纸会审", "设计变更", "技术核定"]),
            VolumeCategory("C3", "施工物资文件", ["材料", "构配件", "设备", "出厂合格证", "检验报告", "进场验收"]),
            VolumeCategory("C4", "施工记录", ["施工记录", "隐蔽", "预检", "交接检查"]),
            VolumeCategory("C5", "施工试验记录", ["试验", "检测", "试压", "试块", "钢筋"]),
            VolumeCategory("C6", "施工质量验收记录", ["检验批", "分项", "分部", "单位工程", "质量验收"]),
            VolumeCategory("C7", "竣工验收文件", ["竣工", "验收", "交工", "竣工验收报告"]),
            VolumeCategory("D", "竣工图", ["竣工图", "建施", "结施", "设施", "电施"]),
            VolumeCategory("E", "工程声像资料", ["照片", "影像", "视频", "声像"]),
        ]
    ),
    "industrial": ProjectType(
        code="industrial",
        name="工业建筑工程",
        volume_categories=[
            VolumeCategory("A", "工程准备阶段文件", ["立项", "可研", "规划", "土地", "勘察", "设计"]),
            VolumeCategory("B", "监理文件", ["监理"]),
            VolumeCategory("C", "施工文件", ["施工"]),
            VolumeCategory("C1", "施工管理文件", ["施工组织", "施工日志"]),
            VolumeCategory("C2", "施工技术文件", ["技术交底", "设计变更"]),
            VolumeCategory("C3", "施工物资文件", ["材料", "设备", "合格证"]),
            VolumeCategory("C4", "施工记录", ["施工记录", "隐蔽"]),
            VolumeCategory("C5", "施工试验记录", ["试验", "检测"]),
            VolumeCategory("C6", "施工质量验收记录", ["检验批", "分项", "分部", "验收"]),
            VolumeCategory("C7", "竣工验收文件", ["竣工", "验收"]),
            VolumeCategory("C8", "工艺设备安装文件", ["工艺", "设备安装", "调试", "试运转"]),
            VolumeCategory("C9", "工业管道安装文件", ["管道", "管廊"]),
            VolumeCategory("D", "竣工图", ["竣工图"]),
            VolumeCategory("E", "工程声像资料", ["照片", "影像"]),
        ]
    ),
    "municipal": ProjectType(
        code="municipal",
        name="市政公用工程",
        volume_categories=[
            VolumeCategory("A", "工程准备阶段文件", ["立项", "可研", "规划", "土地"]),
            VolumeCategory("B", "监理文件", ["监理"]),
            VolumeCategory("C", "施工文件", ["施工"]),
            VolumeCategory("C1", "施工管理文件", ["施工组织", "施工日志"]),
            VolumeCategory("C2", "施工技术文件", ["技术交底", "设计变更"]),
            VolumeCategory("C3", "施工物资文件", ["材料", "构配件", "设备"]),
            VolumeCategory("C4", "施工记录", ["施工记录", "隐蔽"]),
            VolumeCategory("C5", "施工试验记录", ["试验", "检测"]),
            VolumeCategory("C6", "施工质量验收记录", ["检验批", "分项", "分部"]),
            VolumeCategory("C7", "竣工验收文件", ["竣工", "验收"]),
            VolumeCategory("C8", "道路工程文件", ["道路", "路基", "路面"]),
            VolumeCategory("C9", "桥梁工程文件", ["桥梁", "桩基", "桥台"]),
            VolumeCategory("C10", "给排水工程文件", ["给水", "排水", "管网", "井室"]),
            VolumeCategory("D", "竣工图", ["竣工图"]),
            VolumeCategory("E", "工程声像资料", ["照片", "影像"]),
        ]
    ),
}


UNIT_PATTERNS = [
    r'(?P<unit>\d+[#号楼栋单元])',
    r'(?P<unit>第[一二三四五六七八九十百千]+[号楼栋])',
    r'(?P<unit>车库|地下室|人防|配套|商业|办公楼|住宅|厂房|仓库)',
]


DATE_PATTERNS = [
    r'(?P<date>20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}日?)',
    r'(?P<date>20\d{6})',
    r'(?P<date>20\d{2}\d{2}\d{2})',
]


NUMBER_PATTERNS = [
    r'(?P<number>№\s*\d+)',
    r'(?P<number>编号[:：]?\s*\d+)',
    r'(?P<number>\d{2,4}-\d{3,4})',
    r'(?P<number>第[一二三四五六七八九十百千0-9]+[号份])',
]


def parse_filename(filename: str, project_type: str) -> Dict:
    result = {
        "filename": filename,
        "unit": None,
        "category_code": None,
        "category_name": None,
        "date": None,
        "number": None,
        "is_recognized": False,
    }

    name_without_ext = re.sub(r'\.[^.]+$', '', filename)

    for pattern in UNIT_PATTERNS:
        match = re.search(pattern, name_without_ext)
        if match:
            result["unit"] = match.group("unit")
            break

    for pattern in DATE_PATTERNS:
        match = re.search(pattern, name_without_ext)
        if match:
            result["date"] = match.group("date")
            break

    for pattern in NUMBER_PATTERNS:
        match = re.search(pattern, name_without_ext)
        if match:
            result["number"] = match.group("number")
            break

    pt = PROJECT_TYPES.get(project_type)
    if pt:
        all_matches = []
        for vol_cat in pt.volume_categories:
            max_kw_len = 0
            matched_keyword = None
            for keyword in vol_cat.keywords:
                if keyword in name_without_ext and len(keyword) > max_kw_len:
                    max_kw_len = len(keyword)
                    matched_keyword = keyword
            if matched_keyword:
                all_matches.append((max_kw_len, len(vol_cat.code), vol_cat.code, vol_cat.name, matched_keyword))
        if all_matches:
            all_matches.sort(key=lambda x: (-x[0], -x[1]))
            best_match = all_matches[0]
            result["category_code"] = best_match[2]
            result["category_name"] = best_match[3]

    if result["unit"] or result["category_code"]:
        result["is_recognized"] = bool(result["category_code"])

    return result


def get_project_type(project_type_code: str) -> Optional[ProjectType]:
    return PROJECT_TYPES.get(project_type_code)


def list_project_types() -> List[ProjectType]:
    return list(PROJECT_TYPES.values())


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    date_str = re.sub(r'[年月/.日-]', '', date_str)
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str
