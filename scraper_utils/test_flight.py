"""The Next.js flight reader: rows, references, elements."""
import json

from scraper_utils import flight


def page(*chunks):
    return "<html>" + "".join(f"<script>self.__next_f.push([1,{json.dumps(chunk)}])</script>" for chunk in chunks) + "</html>"


TEXT = "line one\nline two: ü"
HTML = page(
    '1:"$Sreact.fragment"\n2:I[123,["a","b"],"default"]\n',
    '3:["$","div","k1",{"className":"entry","children":[["$","$L2",null,{"score":5,"note":"$5","gone":"$undefined"}],"$L4"]}]\n',
    '4:["$","p",null,{"children":"later","price":"$$9"}]\n',
    f'5:T{len(TEXT.encode()):x},{TEXT}6:{{"a":{{"b":1}},"list":[{{"b":2}}]}}\n',
    '7:not json\n8:null\n',
)


def test_rows_reads_json_rows_and_text_rows_by_length():
    rows = flight.rows(HTML)
    assert rows["1"] == "$Sreact.fragment" and rows["5"] == TEXT and rows["6"]["a"] == {"b": 1} and rows["8"] is None
    assert "2" not in rows and "7" not in rows            # a module row and a row that does not parse
    assert flight.rows("") == {} and flight.rows(None) == {} and flight.rows("<html></html>") == {}
    assert flight.text_of(page("a", "b")) == "ab"


def test_resolved_follows_references():
    rows = flight.rows(HTML)
    tree = flight.resolved(rows["3"], rows)
    props = tree[3]["children"][0][3]
    assert props == {"score": 5, "note": TEXT, "gone": None}
    assert tree[3]["children"][1][3] == {"children": "later", "price": "$9"}      # "$L4" followed, "$$9" unescaped
    assert tree[3]["children"][0][1] == "$L2"                                       # a module reference stays
    assert flight.resolved("$Lff", rows) == "$Lff" and flight.resolved(7, rows) == 7
    assert flight.resolved("$a", {"a": "$b", "b": "$a"}) in ("$a", "$b")            # a loop ends


def test_a_text_row_is_raw_text_not_a_reference_or_an_escape():
    money, pointer = "$$ deals $$ all week", "$3"
    rows = flight.rows(page(
        f'1:T{len(money):x},{money}2:T{len(pointer):x},{pointer}3:{{"secret":1}}\n'
        '4:{"about":"$1","other":"$2","escaped":"$$5 off"}\n'))
    assert flight.resolved(rows["4"], rows) == {"about": money, "other": pointer, "escaped": "$5 off"}
    assert flight.resolved(rows["1"], rows) == money and type(flight.resolved("$1", rows)) is str


def test_elements_and_dicts_and_props_with():
    rows = flight.rows(HTML)
    tags = [(tag, key) for tag, key, _props in flight.elements(rows["3"])]
    assert tags == [("div", "k1"), ("$L2", None)]
    assert [d for d in flight.dicts(rows["6"])] == [rows["6"], {"b": 1}, {"b": 2}]
    assert flight.props_with(rows, "score", "note") == [{"score": 5, "note": TEXT, "gone": None}]
    assert flight.props_with(rows, "b") == [{"b": 1}, {"b": 2}] and flight.props_with(rows, "nope") == []
