"""配置加载：profile（站点）/ pages（页面与元素）/ cases（用例）三层。

设计目标：所有"环境相关"的东西都在这里，框架代码里不出现任何具体业务系统。
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

import yaml

# 项目根目录（src/webui_auto/../..）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONFIG_DIR = os.path.join(ROOT, "config")


def _load_dotenv(path: Optional[str] = None) -> None:
    """把项目根 .env 载入环境变量（不覆盖已存在的环境变量）。"""
    p = path or os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def load_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _yaml_files(d: str) -> List[str]:
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if name.lower().endswith((".yaml", ".yml")):
            out.append(os.path.join(d, name))
    return out


def credentials(profile: Dict[str, Any]) -> Dict[str, str]:
    """从 profile.login.credentials 解析账号密码：优先环境变量，其次 default。"""
    login = profile.get("login") or {}
    cr = login.get("credentials") or {}
    out: Dict[str, str] = {}
    # 直接写死的（不推荐，但允许）
    for key in ("username", "password"):
        if cr.get(key):
            out[key] = str(cr[key])
    # 环境变量优先
    for key, env_key, def_key in (
        ("username", "username_env", "username_default"),
        ("password", "password_env", "password_default"),
    ):
        env_name = cr.get(env_key)
        val = os.environ.get(env_name) if env_name else None
        if not val:
            val = cr.get(def_key)
        if val is not None:
            out[key] = str(val)
    return out


VAR_PATTERN = "${"


def resolve_vars(obj: Any, variables: Dict[str, Any]) -> Any:
    """递归把字符串里的 ${name} 替换成变量值。"""
    if isinstance(obj, str):
        if VAR_PATTERN in obj:
            out = obj
            for k, v in variables.items():
                out = out.replace("${" + str(k) + "}", str(v))
            return out
        return obj
    if isinstance(obj, list):
        return [resolve_vars(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve_vars(v, variables) for k, v in obj.items()}
    return obj


class Config:
    """一份完整的运行配置：站点档案 + 页面元素注册表 + 用例列表 + 变量表。"""

    def __init__(
        self,
        profile: Dict[str, Any],
        pages: Dict[str, Any],
        cases: List[Dict[str, Any]],
        config_dir: str,
        profile_name: str,
        variables: Optional[Dict[str, Any]] = None,
    ):
        self.profile = profile or {}
        self.pages = pages or {}
        self.cases = cases or []
        self.config_dir = config_dir
        self.profile_name = profile_name
        self.vars = dict(variables or {})

    # —— 便捷访问 ——
    @property
    def base_url(self) -> str:
        b = (self.profile.get("base_url") or "").rstrip("/")
        # 方便本地静态站点调试：file://./xxx 会按项目根目录解析成绝对路径
        if b.startswith("file://."):
            rel = b[len("file://"):]
            abs_p = os.path.abspath(os.path.join(ROOT, rel))
            return "file:///" + abs_p.replace("\\", "/")
        return b

    @property
    def content_container(self) -> str:
        return self.profile.get("content_container") or "body"

    def timeout(self, key: str, default: int) -> int:
        return int((self.profile.get("timeouts") or {}).get(key, default))

    def page(self, name: str) -> Dict[str, Any]:
        return self.pages.get(name) or {}

    def page_elements(self, name: str) -> Dict[str, Any]:
        return self.page(name).get("elements") or {}

    def element(self, page_name: str, element_name: str) -> Optional[Dict[str, Any]]:
        return self.page_elements(page_name).get(element_name)

    def url_of(self, page_name: str) -> str:
        """页面名 → 完整地址（path 相对 base_url）。"""
        p = self.page(page_name)
        path = p.get("path") or p.get("url") or "/"
        if str(path).startswith("http"):
            return path
        return self.base_url + "/" + str(path).lstrip("/")

    def write_keywords(self) -> List[str]:
        sec = self.profile.get("security") or {}
        return sec.get("write_keywords") or DEFAULT_WRITE_KEYWORDS


DEFAULT_WRITE_KEYWORDS = [
    "新建", "创建", "保存", "删除", "提交", "导入", "导出", "确认", "审核", "发布",
    "新增", "编辑", "上传", "清空", "重置", "付款", "关闭订单",
    "create", "save", "delete", "submit", "import", "confirm", "publish",
]


def load_config(
    config_dir: Optional[str] = None,
    profile_name: Optional[str] = None,
    cli_vars: Optional[Dict[str, Any]] = None,
    base_url_override: Optional[str] = None,
) -> Config:
    """加载全部配置。

    profile_name 为空时：若 cases 里声明了 profile 则按用例分组（这里取第一个显式声明），
    否则尝试加载 profiles 目录下唯一/第一个档案。
    """
    _load_dotenv()
    cfg_dir = config_dir or DEFAULT_CONFIG_DIR

    # 1) 站点档案
    profiles_dir = os.path.join(cfg_dir, "profiles")
    profiles: Dict[str, Any] = {}
    for f in _yaml_files(profiles_dir):
        data = load_yaml(f)
        nm = data.get("name") or os.path.splitext(os.path.basename(f))[0]
        profiles[nm] = data

    # 2) 页面与元素（合并所有 pages 文件）
    pages: Dict[str, Any] = {}
    for f in _yaml_files(os.path.join(cfg_dir, "pages")):
        data = load_yaml(f)
        for k, v in (data.get("pages") or {}).items():
            pages[k] = v

    # 3) 用例
    cases: List[Dict[str, Any]] = []
    for f in _yaml_files(os.path.join(cfg_dir, "cases")):
        data = load_yaml(f)
        suite = data.get("suite")
        suite_profile = data.get("profile")
        defaults = data.get("defaults") or {}
        for c in data.get("cases") or []:
            c = copy.deepcopy(c)
            c.setdefault("tags", defaults.get("tags", []))
            c["_suite"] = suite
            c["_profile"] = c.get("profile") or suite_profile
            c["_file"] = os.path.basename(f)
            cases.append(c)

    # 4) 选定 profile
    name = profile_name
    if not name:
        declared = [c.get("_profile") for c in cases if c.get("_profile")]
        if declared:
            name = declared[0]
        elif profiles:
            name = sorted(profiles.keys())[0]
    if name and name not in profiles:
        raise SystemExit(f"[配置错误] 找不到站点档案 profile='{name}'，已有：{list(profiles)}")
    profile = copy.deepcopy(profiles.get(name, {})) if name else {}

    if base_url_override:
        profile["base_url"] = base_url_override

    # 5) 变量：credentials → cli_vars（后者优先）
    variables: Dict[str, Any] = {}
    variables.update(credentials(profile))
    variables.update(cli_vars or {})

    return Config(profile, pages, cases, cfg_dir, name or "", variables)


def filter_cases(
    cases: List[Dict[str, Any]],
    tags: Optional[List[str]] = None,
    ids: Optional[List[str]] = None,
    names: Optional[List[str]] = None,
    suites: Optional[List[str]] = None,
    profile: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按 tag / id / name / suite / profile 筛选（任一命中即保留）。"""
    def hit(c: Dict[str, Any]) -> bool:
        conds = []
        if tags:
            ct = set(c.get("tags") or [])
            conds.append(bool(ct & set(tags)))
        if ids:
            conds.append(c.get("id") in ids)
        if names:
            nm = str(c.get("name") or "")
            conds.append(any(k in nm for k in names))
        if suites:
            conds.append(c.get("_suite") in suites)
        if profile:
            conds.append((c.get("_profile") or None) == profile)
        if not conds:
            return True
        return any(conds)

    return [c for c in cases if hit(c)]
