def test_audit_package_exports_match_pinned_interfaces():
    from tradeloop.lib.audit import compare, recheck, report
    assert callable(compare) and callable(recheck) and callable(report)
