import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

try:
    from config import config
except ModuleNotFoundError:
    # Support direct execution: `python tools/neo4j_utils.py`
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from config import config

class Neo4jTool:
    def __init__(self):
        if not config.NEO4J_URI or not config.NEO4J_USER or not config.NEO4J_PASSWORD:
            raise ValueError("Missing Neo4j config: set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env")

        self.driver = GraphDatabase.driver(
            config.NEO4J_URI, 
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )

        # Relationship aliases to support different naming conventions in Neo4j.
        self.property_rel_types = ["has property", "Has_property", "HAS_PROPERTY", "has_property"]
        self.composed_rel_types = ["composed of", "Composed_of", "COMPOSED_OF", "composed_of"]
        self.family_rel_types = ["in family", "In_family", "IN_FAMILY", "in_family"]

    def close(self):
        self.driver.close()

    @staticmethod
    def _extract_numeric(value):
        """Extract first numeric token from strings like '1.9 eV' or '15.7 '."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        number = ""
        seen_digit = False
        for ch in text:
            if ch.isdigit():
                number += ch
                seen_digit = True
                continue
            if ch in ".-" and (not number or number[-1].isdigit()):
                number += ch
                continue
            if seen_digit:
                break

        try:
            return float(number) if number else None
        except ValueError:
            return None

    @staticmethod
    def _percentile(values: List[float], q: float) -> Optional[float]:
        """Compute percentile with linear interpolation. q should be in [0, 1]."""
        if not values:
            return None
        if len(values) == 1:
            return float(values[0])

        ordered = sorted(values)
        q = max(0.0, min(1.0, q))
        pos = q * (len(ordered) - 1)
        lower = int(pos)
        upper = min(lower + 1, len(ordered) - 1)
        if lower == upper:
            return float(ordered[lower])
        weight = pos - lower
        return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)

    def get_white_light_property_distribution(self) -> Dict[str, Any]:
        """Collect numeric FWHM/PLQY distributions from KG property nodes."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material)
                OPTIONAL MATCH (m)-[r]->(p)
                WHERE type(r) IN $property_rel_types
                WITH m, collect(DISTINCT p) as props
                RETURN m.formula as formula,
                       [x IN props WHERE x.fwhm IS NOT NULL | x.fwhm] as fwhm_values,
                       [x IN props WHERE x.PLQY IS NOT NULL | x.PLQY] as plqy_values,
                       [x IN props WHERE x.stability IS NOT NULL | x.stability] as stability_values
                """,
                property_rel_types=self.property_rel_types,
            )

            fwhm_all: List[float] = []
            plqy_all: List[float] = []
            stability_count = 0

            for record in result:
                fwhm_values = record.get("fwhm_values") or []
                plqy_values = record.get("plqy_values") or []
                stability_values = record.get("stability_values") or []

                parsed_fwhm = [self._extract_numeric(v) for v in fwhm_values]
                parsed_plqy = [self._extract_numeric(v) for v in plqy_values]
                fwhm_all.extend([v for v in parsed_fwhm if v is not None])
                plqy_all.extend([v for v in parsed_plqy if v is not None])
                if stability_values:
                    stability_count += 1

            return {
                "fwhm": fwhm_all,
                "plqy": plqy_all,
                "materials_with_stability": stability_count,
            }

    def suggest_white_light_constraints(
        self,
        objective: str,
        user_min_fwhm: Optional[float],
        user_min_plqy: Optional[float],
        fallback_min_fwhm: float = 80.0,
        fallback_min_plqy: float = 10.0,
    ) -> Dict[str, Any]:
        """Suggest retrieval constraints using user intent + KG percentiles."""
        dist = self.get_white_light_property_distribution()
        fwhm_values = dist.get("fwhm", [])
        plqy_values = dist.get("plqy", [])
        objective_l = (objective or "").lower()

        # Intent-sensitive percentile policy.
        fwhm_q = 0.70 if any(k in objective_l for k in ["broad", "宽", "white", "白光"]) else 0.60
        plqy_q = 0.80 if any(k in objective_l for k in ["high", "efficient", "高", "效率", "yield"]) else 0.70

        suggested_fwhm = self._percentile(fwhm_values, fwhm_q)
        suggested_plqy = self._percentile(plqy_values, plqy_q)

        min_fwhm = user_min_fwhm
        min_plqy = user_min_plqy
        source = "user"

        if min_fwhm is None:
            min_fwhm = suggested_fwhm if suggested_fwhm is not None else fallback_min_fwhm
            source = "kg" if suggested_fwhm is not None else "fallback"
        if min_plqy is None:
            min_plqy = suggested_plqy if suggested_plqy is not None else fallback_min_plqy
            source = "kg" if source in {"kg", "fallback"} and suggested_plqy is not None else source
            if source == "user" and user_min_fwhm is not None and user_min_plqy is None:
                source = "hybrid"
        if user_min_fwhm is None and user_min_plqy is None and source == "user":
            source = "fallback"
        elif (user_min_fwhm is None) != (user_min_plqy is None):
            if source != "fallback":
                source = "hybrid"

        return {
            "min_fwhm": float(min_fwhm),
            "min_plqy": float(min_plqy),
            "source": source,
            "policy": {
                "fwhm_percentile": fwhm_q,
                "plqy_percentile": plqy_q,
                "fwhm_samples": len(fwhm_values),
                "plqy_samples": len(plqy_values),
            },
        }

    def query_material_props(self, formula):
        """查询特定材料的所有性质（向后兼容旧接口）。"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material {formula: $formula})-[r]->(p)
                WHERE type(r) IN $property_rel_types
                RETURN properties(p) as props,
                       coalesce(p.name, p.property_name) as kv_name,
                       p.value as kv_value
                """,
                formula=formula,
                property_rel_types=self.property_rel_types,
            )

            rows = []
            for record in result:
                kv_name = record.get("kv_name")
                kv_value = record.get("kv_value")
                if kv_name:
                    rows.append({"property": kv_name, "value": kv_value})
                    continue

                props = record.get("props") or {}
                for key, value in props.items():
                    if key == "id" or value is None:
                        continue
                    rows.append({"property": key, "value": value})
            return rows

    def get_material_profile(self, formula: str) -> Dict:
        """返回材料画像：基本信息 + 所有性质 + 组成元素 + 家族。"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material {formula: $formula})
                OPTIONAL MATCH (m)-[rp]->(p)
                WHERE type(rp) IN $property_rel_types
                OPTIONAL MATCH (m)-[rc]->(e:Element)
                WHERE type(rc) IN $composed_rel_types
                OPTIONAL MATCH (m)-[rf]->(f)
                WHERE type(rf) IN $family_rel_types
                RETURN m.formula as formula,
                       collect(DISTINCT properties(p)) as property_rows,
                       collect(DISTINCT e.symbol) as elements,
                       collect(DISTINCT coalesce(f.name, f.family, f.type)) as families
                """,
                formula=formula,
                property_rel_types=self.property_rel_types,
                composed_rel_types=self.composed_rel_types,
                family_rel_types=self.family_rel_types,
            )
            record = result.single()
            if not record:
                return {}

            data = record.data()
            flattened_properties = []
            for row in data.get("property_rows") or []:
                if not row:
                    continue
                for key, value in row.items():
                    if key == "id" or value is None:
                        continue
                    flattened_properties.append({"property": key, "value": value})

            data["properties"] = flattened_properties
            data.pop("property_rows", None)
            return data

    def find_white_light_candidates(
        self,
        min_fwhm: float = 80.0,
        min_plqy: float = 10.0,
        require_stability: bool = True,
        limit: int = 10,
    ) -> List[Dict]:
        """
        按关键性质筛选宽光谱白光候选。
        - `fwhm >= min_fwhm`
        - `PLQY >= min_plqy`
        - 可选包含稳定性信息
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material)
                OPTIONAL MATCH (m)-[r]->(p)
                WHERE type(r) IN $property_rel_types
                WITH m,
                     collect(DISTINCT p) as props
                WITH m,
                     [x IN props WHERE x.fwhm IS NOT NULL | x.fwhm] as fwhm_values,
                     [x IN props WHERE x.PLQY IS NOT NULL | x.PLQY] as plqy_values,
                     [x IN props WHERE x.stability IS NOT NULL | x.stability] as stability_values
                RETURN m.formula as formula,
                       fwhm_values,
                       plqy_values,
                       stability_values
                """,
                property_rel_types=self.property_rel_types,
            )

            candidates = []
            for record in result:
                fwhm_values = record.get("fwhm_values") or []
                plqy_values = record.get("plqy_values") or []
                stability_values = record.get("stability_values") or []

                parsed_fwhm = [self._extract_numeric(v) for v in fwhm_values]
                parsed_plqy = [self._extract_numeric(v) for v in plqy_values]
                parsed_fwhm = [v for v in parsed_fwhm if v is not None]
                parsed_plqy = [v for v in parsed_plqy if v is not None]

                if not parsed_fwhm or not parsed_plqy:
                    continue

                max_fwhm = max(parsed_fwhm)
                max_plqy = max(parsed_plqy)

                if max_fwhm < min_fwhm or max_plqy < min_plqy:
                    continue

                if require_stability and not stability_values:
                    continue

                candidates.append(
                    {
                        "formula": record.get("formula"),
                        "fwhm": max_fwhm,
                        "plqy": max_plqy,
                        "stability": stability_values[0] if stability_values else None,
                    }
                )

            candidates.sort(key=lambda x: (x["plqy"], x["fwhm"]), reverse=True)
            return candidates[:limit]

    def find_similar_materials(
        self,
        formula: str,
        limit: int = 8,
    ) -> List[Dict]:
        """基于元素重叠、家族和结构维度，检索相似铜卤材料。"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (target:Material {formula: $formula})

                OPTIONAL MATCH (target)-[rtc]->(te:Element)
                WHERE type(rtc) IN $composed_rel_types
                WITH target, collect(DISTINCT te.symbol) as target_elements

                OPTIONAL MATCH (target)-[rtf]->(tf)
                WHERE type(rtf) IN $family_rel_types
                WITH target, target_elements, collect(DISTINCT coalesce(tf.name, tf.family, tf.type)) as target_families

                OPTIONAL MATCH (target)-[rtp]->(td)
                WHERE type(rtp) IN $property_rel_types
                 WITH target, target_elements, target_families,
                     collect(DISTINCT td.dimensionality) as target_dims
                 WITH target, target_elements, target_families,
                     CASE WHEN size(target_dims) > 0 THEN target_dims[0] ELSE NULL END as target_dim

                MATCH (cand:Material)
                WHERE cand.formula <> $formula

                OPTIONAL MATCH (cand)-[rcc]->(ce:Element)
                WHERE type(rcc) IN $composed_rel_types
                WITH target, target_elements, target_families, target_dim, cand,
                     collect(DISTINCT ce.symbol) as cand_elements

                OPTIONAL MATCH (cand)-[rcf]->(cf)
                WHERE type(rcf) IN $family_rel_types
                WITH target, target_elements, target_families, target_dim, cand, cand_elements,
                     collect(DISTINCT coalesce(cf.name, cf.family, cf.type)) as cand_families

                OPTIONAL MATCH (cand)-[rcp]->(cd)
                WHERE type(rcp) IN $property_rel_types

                 WITH target_elements, target_families, target_dim,
                     cand, cand_elements, cand_families,
                     collect(DISTINCT cd.dimensionality) as cand_dims,
                     size([x IN cand_elements WHERE x IN target_elements]) as shared_element_count,
                     size([x IN cand_families WHERE x IN target_families]) as shared_family_count
                 WITH cand, shared_element_count, shared_family_count,
                     target_dim,
                     CASE WHEN size(cand_dims) > 0 THEN cand_dims[0] ELSE NULL END as cand_dim
                 WITH cand, shared_element_count, shared_family_count, cand_dim,
                     CASE WHEN target_dim IS NOT NULL AND cand_dim = target_dim THEN 1 ELSE 0 END as dim_match
                WITH cand,
                     cand_dim,
                     shared_element_count,
                     shared_family_count,
                     dim_match,
                     (shared_element_count * 2 + shared_family_count + dim_match) as similarity_score
                WHERE similarity_score > 0
                RETURN cand.formula as formula,
                       similarity_score,
                       shared_element_count,
                       shared_family_count,
                       dim_match,
                       cand_dim as dimensionality
                ORDER BY similarity_score DESC, shared_element_count DESC
                LIMIT $limit
                """,
                formula=formula,
                limit=limit,
                property_rel_types=self.property_rel_types,
                composed_rel_types=self.composed_rel_types,
                family_rel_types=self.family_rel_types,
            )
            return [record.data() for record in result]

    def get_material_evidence(
        self,
        formula: str,
        target_properties: Optional[List[str]] = None,
    ) -> List[Dict]:
        """返回可解释证据路径：Material -> has property -> Property。"""
        target_properties = [p.lower() for p in (target_properties or [])]
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (m:Material {formula: $formula})-[r]->(p)
                WHERE type(r) IN $property_rel_types
                RETURN m.formula as material,
                       type(r) as relation,
                       properties(p) as props
                """,
                formula=formula,
                property_rel_types=self.property_rel_types,
            )

            rows = []
            for record in result:
                props = record.get("props") or {}
                for key, value in props.items():
                    key_l = str(key).lower()
                    if key_l in {"id", "reference", "source_review", "source"}:
                        continue
                    if value is None:
                        continue
                    if target_properties and key_l not in target_properties:
                        continue

                    rows.append(
                        {
                            "material": record.get("material"),
                            "relation": record.get("relation"),
                            "property_name": key_l,
                            "property_value": value,
                            "evidence_source": props.get("reference") or props.get("source_review") or props.get("source"),
                        }
                    )
            rows.sort(key=lambda x: x["property_name"])
            return rows

# 实例化供 Agent 调用
neo4j_tool = Neo4jTool()