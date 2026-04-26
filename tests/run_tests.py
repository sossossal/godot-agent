#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试运行器
运行所有测试并生成报告
"""

import sys
import unittest
from pathlib import Path
from datetime import datetime
import json

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def discover_and_run_tests():
    """发现并运行所有测试"""
    
    console.print("\n[bold cyan]🧪 Godot Agent 测试套件[/bold cyan]\n")
    console.print("="*60)
    
    # 发现测试
    console.print("\n[yellow]📋 发现测试用例...[/yellow]")
    
    test_dir = Path(__file__).parent
    loader = unittest.TestLoader()
    suite = loader.discover(str(test_dir), pattern='test_*.py')
    
    # 统计测试数量
    test_count = suite.countTestCases()
    console.print(f"[green]✅ 找到 {test_count} 个测试用例[/green]\n")
    
    # 运行测试
    console.print("[yellow]🚀 开始运行测试...[/yellow]\n")
    
    runner = unittest.TextTestRunner(verbosity=2)
    
    # 记录开始时间
    start_time = datetime.now()
    
    # 运行测试
    result = runner.run(suite)
    
    # 记录结束时间
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # 生成报告
    generate_report(result, test_count, duration)
    
    return result.wasSuccessful()


def generate_report(result, total_tests, duration):
    """
    生成测试报告
    
    Args:
        result: 测试结果
        total_tests: 总测试数
        duration: 运行时长
    """
    console.print("\n" + "="*60)
    console.print("[bold cyan]📊 测试报告[/bold cyan]")
    console.print("="*60 + "\n")
    
    # 创建统计表
    table = Table(title="测试统计", show_header=True, header_style="bold magenta")
    table.add_column("项目", style="cyan", width=20)
    table.add_column("数量", style="yellow", justify="right")
    
    passed = total_tests - len(result.failures) - len(result.errors)
    
    table.add_row("总测试数", str(total_tests))
    table.add_row("✅ 通过", f"[green]{passed}[/green]")
    table.add_row("❌ 失败", f"[red]{len(result.failures)}[/red]")
    table.add_row("💥 错误", f"[red]{len(result.errors)}[/red]")
    table.add_row("⏱️  耗时", f"{duration:.2f} 秒")
    
    console.print(table)
    console.print()
    
    # 显示失败的测试
    if result.failures:
        console.print("[bold red]❌ 失败的测试:[/bold red]\n")
        for test, traceback in result.failures:
            console.print(f"  • {test}")
            console.print(f"[dim]{traceback}[/dim]\n")
    
    # 显示错误的测试
    if result.errors:
        console.print("[bold red]💥 错误的测试:[/bold red]\n")
        for test, traceback in result.errors:
            console.print(f"  • {test}")
            console.print(f"[dim]{traceback}[/dim]\n")
    
    # 总结
    if result.wasSuccessful():
        console.print(Panel(
            "[bold green]✅ 所有测试通过! 🎉[/bold green]",
            border_style="green"
        ))
    else:
        console.print(Panel(
            f"[bold red]❌ {len(result.failures) + len(result.errors)} 个测试失败[/bold red]",
            border_style="red"
        ))
    
    # 保存 JSON 报告
    save_json_report(result, total_tests, duration)


def save_json_report(result, total_tests, duration):
    """保存 JSON 格式的测试报告"""
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total_tests,
            "passed": total_tests - len(result.failures) - len(result.errors),
            "failed": len(result.failures),
            "errors": len(result.errors),
            "duration": duration
        },
        "failures": [
            {
                "test": str(test),
                "traceback": traceback
            }
            for test, traceback in result.failures
        ],
        "errors": [
            {
                "test": str(test),
                "traceback": traceback
            }
            for test, traceback in result.errors
        ]
    }
    
    report_file = Path(__file__).parent / "test_report.json"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    console.print(f"\n[dim]📄 详细报告已保存到: {report_file}[/dim]\n")


def main():
    """主函数"""
    try:
        success = discover_and_run_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  测试已中断[/yellow]\n")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]❌ 发生错误: {e}[/bold red]\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
