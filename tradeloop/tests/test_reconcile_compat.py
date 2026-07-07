def test_audit_compare_reexported_from_portfolio_path():
    from tradeloop.lib.portfolio.reconcile import compare as compat_compare
    from tradeloop.lib.audit.reconcile import compare as audit_compare
    assert compat_compare is audit_compare
