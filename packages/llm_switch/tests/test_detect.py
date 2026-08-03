from llm_switch import detect


def test_localhost_is_local():
    assert detect.is_local("http://localhost:11434") is True


def test_127_is_local():
    assert detect.is_local("http://127.0.0.1:11434") is True


def test_private_ip_is_local():
    assert detect.is_local("http://192.168.1.50:8080") is True
    assert detect.is_local("http://10.0.0.5:8080") is True
    assert detect.is_local("http://172.16.0.5:8080") is True


def test_tailscale_cgnat_is_local():
    assert detect.is_local("http://100.64.0.1:8080") is True
    assert detect.is_local("http://100.100.100.100:8080") is True


def test_tailscale_outside_cgnat_is_not_local():
    # 100.x outside the /10 CGNAT block must NOT be misclassified as local
    assert detect.is_local("http://100.50.0.1:8080") is False


def test_dot_local_hostname_is_local():
    assert detect.is_local("http://myhost.local:8080") is True


def test_public_https_is_not_local():
    assert detect.is_local("https://api.deepseek.com") is False
    assert detect.is_local("https://api.anthropic.com") is False


def test_kind_override_local_wins():
    assert detect.is_local("https://api.deepseek.com", kind="local") is True


def test_kind_override_api_wins():
    assert detect.is_local("http://localhost:11434", kind="api") is False


def test_provider_anthropic():
    assert detect.detect_provider("https://api.anthropic.com") == "anthropic"


def test_provider_anthropic_subdomain():
    assert detect.detect_provider("https://eu.api.anthropic.com") == "anthropic"


def test_provider_ollama_by_port():
    assert detect.detect_provider("http://localhost:11434") == "ollama"


def test_provider_ollama_by_api_path():
    assert detect.detect_provider("http://localhost:11434/api") == "ollama"


def test_provider_openai_fallback_generic_https():
    assert detect.detect_provider("https://api.deepseek.com") == "openai"
    assert detect.detect_provider("https://api.openai.com") == "openai"


def test_provider_ollama_v1_path_is_not_native_ollama():
    # Ollama's OpenAI-compat /v1 surface should fall through to "openai"
    assert detect.detect_provider("http://localhost:11434/v1") == "openai"
