import subprocess


def run(prompt: str, wrapper_path: str, cwd: str, timeout: int, env: dict):
    return subprocess.run(
        [wrapper_path],
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
        shell=False,
    )
