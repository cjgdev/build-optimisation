import networkx as nx
import pandas as pd
import pytest

from buildanalysis.types import AnalysisScope, BuildGraph


class TestAnalysisScope:
    def test_global_scope_passes_through(self):
        scope = AnalysisScope()
        df = pd.DataFrame({"cmake_target": ["a", "b", "c"], "value": [1, 2, 3]})
        result = scope.filter_targets(df)
        assert len(result) == 3

    def test_target_filter(self):
        scope = AnalysisScope(targets=frozenset(["a", "c"]))
        df = pd.DataFrame({"cmake_target": ["a", "b", "c"], "value": [1, 2, 3]})
        result = scope.filter_targets(df)
        assert len(result) == 2
        assert set(result["cmake_target"]) == {"a", "c"}

    def test_file_filter(self):
        scope = AnalysisScope(files=frozenset(["/src/foo.cpp"]))
        df = pd.DataFrame({"source_file": ["/src/foo.cpp", "/src/bar.cpp"], "v": [1, 2]})
        result = scope.filter_files(df)
        assert len(result) == 1

    def test_custom_column_name(self):
        scope = AnalysisScope(targets=frozenset(["x"]))
        df = pd.DataFrame({"target_name": ["x", "y"], "v": [1, 2]})
        result = scope.filter_targets(df, col="target_name")
        assert len(result) == 1

    def test_is_global(self):
        assert AnalysisScope().is_global()
        assert not AnalysisScope(targets=frozenset(["a"])).is_global()

    def test_frozen(self):
        scope = AnalysisScope()
        with pytest.raises(AttributeError):
            scope.label = "modified"


class TestBuildGraph:
    @pytest.fixture
    def diamond(self):
        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "target_type": ["executable", "static_library", "static_library", "static_library"],
            }
        ).set_index("cmake_target")
        return BuildGraph(graph=g, target_metadata=meta)

    def test_properties(self, diamond):
        assert diamond.n_targets == 4
        assert diamond.n_edges == 4

    def test_subgraph_includes_transitive_deps(self, diamond):
        scope = AnalysisScope(targets=frozenset(["A"]))
        sub = diamond.subgraph(scope)
        # A depends on B, C; B and C depend on D. So subgraph should have all 4.
        assert sub.n_targets == 4

    def test_subgraph_partial(self, diamond):
        scope = AnalysisScope(targets=frozenset(["B"]))
        sub = diamond.subgraph(scope)
        # B depends on D. Subgraph should have B and D.
        assert sub.n_targets == 2
        assert set(sub.graph.nodes()) == {"B", "D"}

    def test_executables(self, diamond):
        exes = diamond.executables()
        assert exes == ["A"]
