import pytest

import qlik_expr as q
from qlik_script import parse_script, plain_tables


def test_parses_set_analysis_with_operators():
    node = q.parse("Sum({$<[Carrier's Operating Region] = {'Latin America'}, Year = {2011}> "
                   "+ <Year = {2010}> - <[Carrier Group] = {'Foreign Carrier'}>} [# Departures Performed])")
    assert isinstance(node, q.Agg) and node.func == "sum"
    assert isinstance(node.set_expr, q.SetOp) and node.set_expr.op == "-"


def test_total_and_aggr():
    node = q.parse("Sum(x) / Sum(TOTAL <[Carrier Group], Year> x)")
    assert node.right.total == ["Carrier Group", "Year"]
    node = q.parse("Avg(Aggr(Sum(a) / Sum(b), Airline, [From - To Airport ID]))")
    assert isinstance(node.arg, q.Aggr) and node.arg.dims == ["Airline", "From - To Airport ID"]


@pytest.mark.parametrize("expr", ["Above(Sum(x))", "Rank(Sum(x))", "Concat(x, ',')"])
def test_unsupported_is_reported_not_guessed(expr):
    with pytest.raises(q.Unsupported):
        q.parse(expr)


def test_alternate_states_element_functions_and_dimensionality():
    node = q.parse("Sum({[Group A] * $} x)")
    assert node.set_expr.left.identifier == "Group A" and node.set_expr.right.identifier == "$"
    mod = q.parse("Sum({1<Year = e(Year)>} x)").set_expr.modifiers[0]
    assert mod.field == "Year" and mod.values == [("e", ("Year", None))]
    node = q.parse("Pick(Dimensionality() + 1, Sum(a), Sum(b))")
    assert node.name == "pick" and node.args[0].left.name == "dimensionality"
    assert q.expand_dollars("$($(=eMetric))", {}, lambda e: "") == ""


def test_dollar_expansion():
    variables = {"eLF": "(Sum(a) / Sum(b))", "vSet": "Year = {$1}"}
    assert q.expand_dollars("$(eLF) * 2", variables) == "(Sum(a) / Sum(b)) * 2"
    assert q.expand_dollars("Sum({$<$(vSet(2010))>} x)", variables) == "Sum({$<Year = {2010}>} x)"
    assert q.expand_dollars("{$(=Max(Year)-1)}", {}, lambda e: "2010") == "{2010}"
    with pytest.raises(q.Unsupported):
        q.expand_dollars("$(vMissing)", variables)


def test_script_reader_plain_vs_derived():
    script = """
    [Main Data]: LOAD [%Key], [# Value], Year FROM [..\\Data Files\\QVDs\\Flight Data.qvd] (qvd);
    Dim: LOAD [%Key], Name FROM [dim.qvd] (qvd) WHERE Exists([%Key]);
    [Origin Airports]: LOAD `%Origin Airport ID`, `Origin Airport`; SQL SELECT * FROM `Origin Airports`;
    LEFT JOIN ([Main Data]) LOAD [%Key], Extra FROM [x.qvd] (qvd);
    Other: LOAD a as b, c FROM [y.qvd] (qvd);
    """
    assert set(plain_tables(script)) == {"Origin Airports", "Other"}
    loads = parse_script(script)
    assert loads[2].source_kind == "sql" and loads[2].source == "Origin Airports"
    assert [(f.source_name, f.name) for f in loads[4].fields] == [("a", "b"), ("c", "c")]


def test_parity_key_keeps_literal_contents():
    from harness import parity_key
    assert parity_key("Sum ( [# Departures Performed] )") == parity_key("SUM([# Departures Performed])")
    assert parity_key("Sum({<Airline={'A B'}>} x)") != parity_key("Sum({<Airline={'AB'}>} x)")
    assert parity_key("Sum({<Airline={'ab'}>} x)") != parity_key("Sum({<Airline={'AB'}>} x)")
    assert parity_key("Sum([a b])") != parity_key("Sum([ab])")
