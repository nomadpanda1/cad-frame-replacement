# -*- coding: utf-8 -*-
"""
属性迁移：把旧图提取到的 {concept: value} 对齐到模板字段。
优先用显式 override（模板 tag -> 旧 concept），否则按 concept 直接匹配。
返回 (values, unmatched, unused)：
  values    : 与 template_fields 对齐的值列表（缺失为 ""）
  unmatched : 模板中没找到来源的字段 prompt
  unused    : 旧图有但模板没有的字段 concept
"""


def map_fields(template_fields, old_fields, override=None):
    override = override or {}
    values = []
    unmatched = []
    used_concepts = set()
    for tf in template_fields:
        tag = tf["tag"]
        concept = tf["concept"]
        val = ""
        if tag in override and override[tag] in old_fields:
            val = old_fields[override[tag]]
            used_concepts.add(override[tag])
        elif concept in old_fields:
            val = old_fields[concept]
            used_concepts.add(concept)
        if not val:
            unmatched.append(tf.get("prompt") or tag)
        values.append(val)
    unused = [c for c in old_fields if c not in used_concepts and old_fields[c]]
    return values, unmatched, unused
