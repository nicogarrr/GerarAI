from app.services.connectors.edgartools_concepts import concept_to_metric, metric_concepts


def test_pretax_income_domestic_and_foreign_maps_to_income_before_tax():
    tag = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomesticAndForeign"
    assert concept_to_metric(tag) == "income_before_tax"


def test_interest_expense_tags_map_and_real_sec_casing_is_first():
    tags = metric_concepts("interest_expense")
    assert tags[0] == "InterestExpenseNonoperating"
    for tag in ("InterestExpenseDebt", "InterestExpenseLongTermDebt", "InterestAndDebtExpense"):
        assert concept_to_metric(tag) == "interest_expense"


def test_combined_debt_tag_keeps_priority_over_components():
    tags = metric_concepts("total_debt")
    assert tags[0] == "DebtLongtermAndShorttermCombinedAmount"
    assert "LongTermDebtAndCapitalLeaseObligations" in tags
