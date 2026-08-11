# -*- coding: utf-8 -*-
"""Build the final, JSON-safe mapping from iso_match output."""
from __future__ import annotations

from datetime import datetime
import hashlib
import os
from typing import Callable, Optional

import pandas as pd

from utils.utils_common import normalize_line_v2


MATCH_TYPE_SCORES = {
    "strict": 1.0,
    "strip_size": 0.95,
    "drop_last_seg": 0.85,
    "fallback_base": 0.7,
    "fuzzy_manual": 0.9,
    "loose_only": 0.5,
}


OUTPUT_COLUMNS = [
    "Resolved",
    "ResolutionStatus",
    "ResolutionReason",
    "ResolvedAt",
    "ResolvedBy",
    "流水號",
    "管線編號",
    "ISO_Match_Key",
    "Raw_3D_PipeCode",
    "PipeNodePath",
    "ScopeRoot",
    "ParentArea",
    "PipeNodeLevel",
    "MatchType",
    "MatchScore",
    "MatchSource",
    "ConfidencePrimary",
    "IdentityReason",
    "CollisionCount",
    "CollisionParents",
    "NeedsDecision",
    "IsoFamilyKey",
    "ItemIdentityKey",
    "OwnershipStatus",
    "OwnershipOwners",
    "群組",
]


_NATIVE_ITEM_ID_COLUMNS = (
    "NavisGuid",
    "NavisGUID",
    "Navis_GUID",
    "ItemGuid",
    "ItemGUID",
    "ElementGuid",
    "ElementGUID",
)


def _read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet = "結果" if "結果" in xls.sheet_names else xls.sheet_names[0]
        try:
            df = pd.read_excel(xls, sheet_name=sheet, dtype=str).fillna("")
        finally:
            try:
                xls.close()
            except Exception:
                pass
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return df.rename(columns={c: str(c).strip() for c in df.columns})


def _read_iso_source(path: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """Read the original ISO source used to restore business metadata."""

    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(path, engine="openpyxl")
        if sheet_name:
            if sheet_name not in xls.sheet_names:
                xls.close()
                raise ValueError(
                    f"ISO 原始清單找不到工作表：{sheet_name}"
                )
            selected_sheet = sheet_name
        elif "DWG NO.ALL" in xls.sheet_names:
            selected_sheet = "DWG NO.ALL"
        else:
            selected_sheet = xls.sheet_names[0]
        try:
            source = pd.read_excel(
                xls,
                sheet_name=selected_sheet,
                dtype=str,
            ).fillna("")
        finally:
            try:
                xls.close()
            except Exception:
                pass
    else:
        source = pd.read_csv(
            path,
            dtype=str,
            encoding="utf-8-sig",
        ).fillna("")
    return source.rename(columns={c: str(c).strip() for c in source.columns})


_SOURCE_METADATA_PROTECTED = set(OUTPUT_COLUMNS) | {
    "CandidateCount",
    "CandidateTrace",
    "DecisionState",
    "DecisionSource",
    "EvidenceClass",
    "ReasonCodes",
}


def _new_metadata_stats() -> dict[str, int | str]:
    return {
        "source_rows": 0,
        "joined_rows": 0,
        "backfilled_rows": 0,
        "backfilled_cells": 0,
        "metadata_conflicts": 0,
        "ambiguous_spools": 0,
        "skipped": 0,
        "errors": 0,
        "error": "",
    }


def _backfill_iso_source_metadata(
    df: pd.DataFrame,
    source_path: str,
    *,
    source_sheet_name: Optional[str] = None,
    source_spool_col: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, int | str]]:
    """Fill blank ISO business columns from the original source by serial.

    Metadata carried through the normal matching path remains authoritative.
    This join is a recovery net for old review cases and legacy outputs that
    only retained ``iso_spool``.  Ambiguous source serials are never guessed.
    """

    stats = _new_metadata_stats()
    source = _read_iso_source(source_path, source_sheet_name)
    stats["source_rows"] = int(len(source))
    spool_col = str(source_spool_col or "流水號").strip()
    if spool_col not in source.columns:
        raise ValueError(f"ISO 原始清單找不到流水號欄位：{spool_col}")
    if "流水號" not in df.columns:
        raise ValueError("iso_match 缺少流水號欄位，無法回填 ISO metadata")

    source = source.copy()
    source["__metadata_spool"] = source[spool_col].astype(str).str.strip()
    source = source[source["__metadata_spool"].ne("")]
    duplicate_mask = source["__metadata_spool"].duplicated(keep=False)
    stats["ambiguous_spools"] = int(
        source.loc[duplicate_mask, "__metadata_spool"].nunique()
    )
    source = source[~duplicate_mask].drop_duplicates(
        subset=["__metadata_spool"],
        keep="first",
    )
    source = source.set_index("__metadata_spool", drop=True)

    result = df.copy()
    target_spools = result["流水號"].astype(str).str.strip()
    stats["joined_rows"] = int(target_spools.isin(source.index).sum())
    rows_backfilled = pd.Series(False, index=result.index)

    for column in source.columns:
        column_name = str(column).strip()
        if (
            not column_name
            or column_name.startswith("__")
            or column_name in _SOURCE_METADATA_PROTECTED
            or column_name == spool_col
        ):
            continue
        if column_name not in result.columns:
            result[column_name] = ""
        target_values = result[column_name].fillna("").astype(str).str.strip()
        source_values = target_spools.map(source[column_name]).fillna("")
        source_values = source_values.astype(str).str.strip()
        fill_mask = target_values.eq("") & source_values.ne("")
        conflict_mask = (
            target_values.ne("")
            & source_values.ne("")
            & target_values.ne(source_values)
        )
        if fill_mask.any():
            result.loc[fill_mask, column_name] = source_values[fill_mask]
            rows_backfilled |= fill_mask
            stats["backfilled_cells"] += int(fill_mask.sum())
        stats["metadata_conflicts"] += int(conflict_mask.sum())

    stats["backfilled_rows"] = int(rows_backfilled.sum())
    return result, stats


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _to_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def _score_match(
    match_type: object,
    confidence: object,
    explicit_score: object = "",
) -> float:
    explicit = _to_float(explicit_score)
    if explicit > 0:
        return explicit
    mt = str(match_type).strip()
    if mt in MATCH_TYPE_SCORES:
        return MATCH_TYPE_SCORES[mt]
    return _to_float(confidence)


def _file_revision(path: str) -> str:
    """Return a short immutable fingerprint for fallback ITEM identities."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _iso_family_key(value: object) -> str:
    """Build an exact family key without erasing identity punctuation."""

    text = str(value).strip()
    if not text:
        return ""
    normalized, _events = normalize_line_v2(text)
    return (normalized or text).strip().upper()


def _native_item_id(row: pd.Series) -> str:
    for column in _NATIVE_ITEM_ID_COLUMNS:
        value = str(row.get(column, "")).strip()
        if value:
            return f"native:{column}:{value}"
    return ""


def _item_identity_key(row: pd.Series, dataset_revision: str) -> str:
    """Create a run-scoped ITEM identity used by the ownership invariant.

    Native Navis/element GUIDs are preferred.  The fallback intentionally keeps
    scope, full tree path, level and the original 3D value.  When none of the
    structural fields is available we abstain instead of pretending that a raw
    pipe code uniquely identifies an ITEM.
    """

    native = _native_item_id(row)
    if native:
        return native

    scope = str(row.get("ScopeRoot", "")).strip()
    path = str(row.get("PipeNodePath", "")).strip()
    level = str(row.get("PipeNodeLevel", "")).strip()
    raw = str(row.get("Raw_3D_PipeCode", "")).strip()
    if not raw or not any((scope, path, level)):
        return ""

    material = "\x1f".join((scope, path, level, raw))
    item_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"fallback:{dataset_revision}:{item_hash}"


def build_resolved_mapping(
    iso_match_path: str,
    output_path: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    dataset_revision: Optional[str] = None,
    iso_source_path: Optional[str] = None,
    iso_source_sheet: Optional[str] = None,
    iso_source_spool_col: Optional[str] = None,
) -> dict[str, int | str]:
    """Create ``resolved_mapping.csv`` from ``iso_match.xlsx``.

    Rows with collisions are retained for audit but marked ``Resolved=0`` so
    JSON export can skip them by default.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not os.path.exists(iso_match_path):
        raise FileNotFoundError(f"找不到 iso_match 檔案：{iso_match_path}")

    df = _read_table(iso_match_path)
    if "Raw_3D_PipeCode" not in df.columns and "Raw_last" in df.columns:
        df = df.rename(columns={"Raw_last": "Raw_3D_PipeCode"})
    if "Raw_3D_PipeCode" not in df.columns:
        raise ValueError("iso_match 缺少必要欄位 Raw_3D_PipeCode")

    metadata_stats = _new_metadata_stats()
    if iso_source_path:
        try:
            if not os.path.exists(iso_source_path):
                raise FileNotFoundError(
                    f"找不到 ISO 原始清單：{iso_source_path}"
                )
            # Backfill works on a copy and is assigned only after full success,
            # so a partial read/join can never overwrite the core mapping.
            enriched_df, metadata_stats = _backfill_iso_source_metadata(
                df,
                iso_source_path,
                source_sheet_name=iso_source_sheet,
                source_spool_col=iso_source_spool_col,
            )
        except Exception as exc:
            metadata_stats = _new_metadata_stats()
            metadata_stats["skipped"] = 1
            metadata_stats["errors"] = 1
            metadata_stats["error"] = f"{type(exc).__name__}: {exc}"
            _log(
                "[ResolvedMapping] ISO metadata 回填略過（fail-soft）："
                f"source={iso_source_path}, "
                f"error={metadata_stats['error']}"
            )
        else:
            df = enriched_df
            _log(
                "[ResolvedMapping] ISO metadata 回填："
                f"joined={metadata_stats['joined_rows']}, "
                f"rows={metadata_stats['backfilled_rows']}, "
                f"cells={metadata_stats['backfilled_cells']}, "
                f"conflicts={metadata_stats['metadata_conflicts']}, "
                f"ambiguous_spools={metadata_stats['ambiguous_spools']}"
            )

    output_columns = list(OUTPUT_COLUMNS)
    for col in df.columns:
        col_name = str(col).strip()
        if not col_name or col_name.startswith("__"):
            continue
        if col_name not in output_columns:
            output_columns.append(col_name)

    for col in output_columns:
        if col not in df.columns:
            df[col] = ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dataset_revision = str(dataset_revision or _file_revision(iso_match_path)).strip()
    df["Raw_3D_PipeCode"] = df["Raw_3D_PipeCode"].astype(str).str.strip()
    df["NeedsDecision"] = df["NeedsDecision"].astype(str).str.strip()
    df["MatchScore"] = df.apply(
        lambda r: _score_match(
            r.get("MatchType", ""),
            r.get("ConfidencePrimary", ""),
            r.get("MatchScore", ""),
        ),
        axis=1,
    )

    # A 3D ITEM may appear in several rows/spools belonging to the same ISO
    # family, but it must not silently acquire two different ISO identities.
    # This is deliberately independent from fuzzy score and collision ranking.
    df["IsoFamilyKey"] = df["管線編號"].apply(_iso_family_key)
    df["ItemIdentityKey"] = df.apply(
        lambda row: _item_identity_key(row, dataset_revision),
        axis=1,
    )
    ownership_by_item: dict[str, list[str]] = {}
    for item_key, sub in df[df["ItemIdentityKey"].astype(str).ne("")].groupby(
        "ItemIdentityKey",
        sort=False,
    ):
        owners = list(
            dict.fromkeys(
                family
                for family in sub["IsoFamilyKey"].astype(str).tolist()
                if family
            )
        )
        ownership_by_item[str(item_key)] = owners

    df["OwnershipOwners"] = df["ItemIdentityKey"].apply(
        lambda key: " | ".join(ownership_by_item.get(str(key), []))
    )
    df["OwnershipStatus"] = df["ItemIdentityKey"].apply(
        lambda key: (
            "unverifiable"
            if not str(key).strip()
            else (
                "conflict"
                if len(ownership_by_item.get(str(key), [])) > 1
                else "claimed"
            )
        )
    )
    ownership_conflict = df["OwnershipStatus"].eq("conflict")
    if ownership_conflict.any():
        df.loc[ownership_conflict, "NeedsDecision"] = "1"

    statuses: list[str] = []
    reasons: list[str] = []
    resolved_flags: list[int] = []
    for _, row in df.iterrows():
        raw = str(row.get("Raw_3D_PipeCode", "")).strip()
        if not raw:
            resolved_flags.append(0)
            statuses.append("no_raw")
            reasons.append("沒有可輸出的 3D Raw_3D_PipeCode")
        elif str(row.get("OwnershipStatus", "")).strip() == "conflict":
            resolved_flags.append(0)
            statuses.append("ownership_conflict")
            owners = str(row.get("OwnershipOwners", "")).strip()
            reasons.append(
                "同一 3D ITEM 被指派到多個 ISO 家族，已由單一歸屬鎖阻擋"
                + (f"：{owners}" if owners else "")
            )
        elif _truthy(row.get("NeedsDecision", "")):
            resolved_flags.append(0)
            statuses.append("needs_decision")
            reasons.append("同一流水號對應多個 ParentArea/ScopeRoot，需人工決定")
        else:
            resolved_flags.append(1)
            statuses.append("auto")
            reasons.append("非碰撞列，自動納入 JSON-safe mapping")

    df["Resolved"] = resolved_flags
    df["ResolutionStatus"] = statuses
    df["ResolutionReason"] = reasons
    df["ResolvedAt"] = now
    df["ResolvedBy"] = df.apply(
        lambda r: (
            "user"
            if int(r.get("Resolved", 0)) == 1
            and str(r.get("MatchType", "")).strip() == "fuzzy_manual"
            else ("auto" if int(r.get("Resolved", 0)) == 1 else "")
        ),
        axis=1,
    )

    result = df[output_columns].drop_duplicates(
        subset=[
            "Resolved",
            "ResolutionStatus",
            "流水號",
            "Raw_3D_PipeCode",
            "PipeNodePath",
            "ScopeRoot",
            "ParentArea",
            "PipeNodeLevel",
        ],
        keep="first",
    )

    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(iso_match_path)),
            "resolved_mapping.csv",
        )
    result.to_csv(output_path, index=False, encoding="utf-8-sig")

    identity_index_path = ""
    minus1_path = os.path.join(
        os.path.dirname(os.path.abspath(output_path)),
        "123_minus_1.csv",
    )
    if os.path.exists(minus1_path):
        try:
            from core.identity_index import build_identity_index

            identity_index_path = build_identity_index(
                output_path,
                minus1_path,
            )
            _log(f"[ResolvedMapping] 已建立調查索引：{identity_index_path}")
        except Exception as exc:
            _log(f"[ResolvedMapping] 調查索引建立失敗，略過：{exc}")

    total = int(len(result))
    resolved = int((result["Resolved"].astype(str) == "1").sum())
    needs = int(result["NeedsDecision"].apply(_truthy).sum())
    no_raw = int((result["ResolutionStatus"] == "no_raw").sum())
    ownership_conflicts = int(
        (result["ResolutionStatus"] == "ownership_conflict").sum()
    )
    ownership_unverifiable = int(
        (result["OwnershipStatus"] == "unverifiable").sum()
    )
    _log(
        f"[ResolvedMapping] 已輸出 {output_path}，"
        f"resolved={resolved}, needs_decision={needs}, no_raw={no_raw}, "
        f"ownership_conflicts={ownership_conflicts}, "
        f"ownership_unverifiable={ownership_unverifiable}, total={total}"
    )

    return {
        "path": output_path,
        "identity_index_path": identity_index_path,
        "total": total,
        "resolved": resolved,
        "needs_decision": needs,
        "no_raw": no_raw,
        "ownership_conflicts": ownership_conflicts,
        "ownership_unverifiable": ownership_unverifiable,
        "metadata_source_rows": metadata_stats["source_rows"],
        "metadata_joined_rows": metadata_stats["joined_rows"],
        "metadata_backfilled_rows": metadata_stats["backfilled_rows"],
        "metadata_backfilled_cells": metadata_stats["backfilled_cells"],
        "metadata_conflicts": metadata_stats["metadata_conflicts"],
        "metadata_ambiguous_spools": metadata_stats["ambiguous_spools"],
        "metadata_skipped": metadata_stats["skipped"],
        "metadata_errors": metadata_stats["errors"],
        "metadata_error": metadata_stats["error"],
    }
