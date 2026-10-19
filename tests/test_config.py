from agent.config import load_settings


def test_paths_relative_to_env(tmp_path):
    env = tmp_path / "sub" / ".env"
    env.parent.mkdir()
    env.write_text("DATA_DIR=my/data\n")
    s = load_settings(env)
    assert s.data_dir == (tmp_path / "sub" / "my" / "data").resolve()
    assert s.corpus_dir == (tmp_path / "sub" / "data" / "corpus").resolve()


def test_missing_env_uses_defaults(tmp_path):
    s = load_settings(tmp_path / ".env")
    assert s.eval_cases_dir == (tmp_path / "eval" / "cases").resolve()
