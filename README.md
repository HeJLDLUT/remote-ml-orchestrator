# Remote ML Orchestrator

一个用于通过 SSH 在多台 Linux CPU/GPU 服务器上安全、可复现地运行机器学习实验的 Codex Skill。

主要功能包括服务器资源探测、环境构建、负载感知任务分配、断点续跑、运行监控、结果回传以及完整性与科学性验证。

本项目用于大连理工大学陈景文课题组。

## 使用

将本仓库放入 Codex skills 目录后，通过 `$remote-ml-orchestrator` 调用。
