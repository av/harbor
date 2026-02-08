import { prompts } from './judge.ts';

export const summaryTemplate = (data: unknown) => `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Harbor Bench</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        h1, h2, h3 {
            color: #2c3e50;
        }
        .summary {
            background-color: #f8f9fa;
            border-radius: 5px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .chart-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .chart-container {
            background-color: #fff;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            padding: 15px;
            height: 360px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
    </style>
</head>
<body>
    <h1>Bench</h1>
    <div class="summary">
        <h2>Summary</h2>
        <p>Total tasks: <span id="totalTasks"></span></p>
        <p>Overall success rate: <span id="overallSuccessRate"></span>%</p>
        <p>Average task duration: <span id="averageTaskDuration"></span> ms</p>
        <p>Task duration range: <span id="minTaskDuration"></span> ms - <span id="maxTaskDuration"></span> ms</p>
    </div>
    <h2>Results</h2>
    <div id="chartGrid" class="chart-grid"></div>
    <h2>Detailed Results</h2>
    <table id="resultsTable">
        <thead>
            <tr>
                <th>Task ID</th>
                <th>Result</th>
                <th>Tags</th>
                <th>Duration (ms)</th>
                <th>LLM Model</th>
                <th>Judge Model</th>
            </tr>
        </thead>
        <tbody>
        </tbody>
    </table>
    <script>
        const data = ${JSON.stringify(data)};
        // Calculate summary statistics
        const totalTasks = data.length;
        const successfulTasks = data.filter(task => task.result === 1).length;
        const overallSuccessRate = (successfulTasks / totalTasks * 100).toFixed(2);
        const taskDurations = data.map(task => task.time);
        const averageTaskDuration = (taskDurations.reduce((a, b) => a + b, 0) / totalTasks).toFixed(2);
        const minTaskDuration = Math.min(...taskDurations);
        const maxTaskDuration = Math.max(...taskDurations);
        document.getElementById('totalTasks').textContent = totalTasks;
        document.getElementById('overallSuccessRate').textContent = overallSuccessRate;
        document.getElementById('averageTaskDuration').textContent = averageTaskDuration;
        document.getElementById('minTaskDuration').textContent = minTaskDuration;
        document.getElementById('maxTaskDuration').textContent = maxTaskDuration;
        // Function to create a chart
        const createChart = (elementId, labels, data, label) => {
            const ctx = document.getElementById(elementId).getContext('2d');
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: label,
                        data: data,
                        backgroundColor: 'rgba(75, 192, 192, 0.6)',
                        borderColor: 'rgba(75, 192, 192, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const successRate = context.parsed.y;
                                    const label = context.dataset.label || '';
                                    return \`\${label}: \${successRate}%\`;
                                }
                            }
                        }
                    }
                }
            });
        };
        // Function to create a chart container
        const createChartContainer = (id, title) => {
            const container = document.createElement('div');
            container.className = 'chart-container';
            container.innerHTML = \`
                <h3>\${title}</h3>
                <canvas id="\${id}" height="250"></canvas>
            \`;
            return container;
        };
        // Generate charts for each dimension
        const chartGrid = document.getElementById('chartGrid');
        const dimensions = Object.keys(data[0]).filter(key => key.startsWith('llm.') && key !== 'llm.apiKey');
        dimensions.forEach(dimension => {
            const dimensionData = {};
            data.forEach(task => {
                const value = task[dimension];
                if (!dimensionData[value]) {
                    dimensionData[value] = { count: 0, success: 0 };
                }
                dimensionData[value].count++;
                if (task.result === 1) dimensionData[value].success++;
            });
            const chartId = \`chart-\${dimension}\`;
            const chartContainer = createChartContainer(chartId, \`Results by \${dimension}\`);
            chartGrid.appendChild(chartContainer);
            const labels = Object.keys(dimensionData);
            const chartData = Object.values(dimensionData).map(d => (d.success / d.count * 100).toFixed(2));
            createChart(chartId, labels, chartData, 'Success Rate (%)');
        });
        // Create chart for tags
        const tagData = {};
        data.forEach(task => {
            task.tags.forEach(tag => {
                if (!tagData[tag]) tagData[tag] = { count: 0, success: 0 };
                tagData[tag].count++;
                if (task.result === 1) tagData[tag].success++;
            });
        });
        const tagChartId = 'chart-tags';
        const tagChartContainer = createChartContainer(tagChartId, 'Results by Tag');
        chartGrid.appendChild(tagChartContainer);
        const tagLabels = Object.keys(tagData);
        const tagChartData = Object.values(tagData).map(d => (d.success / d.count * 100).toFixed(2));
        createChart(tagChartId, tagLabels, tagChartData, 'Success Rate (%)');
        // Populate results table
        const tableBody = document.getElementById('resultsTable').querySelector('tbody');
        data.forEach(task => {
            const row = tableBody.insertRow();
            row.insertCell(0).textContent = task.id;
            row.insertCell(1).textContent = task.result === 1 ? 'Success' : 'Failure';
            row.insertCell(2).textContent = task.tags.join(', ');
            row.insertCell(3).textContent = task.time;
            row.insertCell(4).textContent = task['llm.model'];
            row.insertCell(5).textContent = task['judge.model'];
        });
    </script>
</body>
</html>
`;

export const runsTemplate = (runs: unknown) => {
    const htmlContent = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task Report</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f0f4f8;
        }
        h1, h2, h3 {
            color: #2c3e50;
        }
        h1 {
            text-align: center;
            color: #34495e;
            margin-bottom: 30px;
        }
        .section {
            background-color: #ffffff;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .task {
            background-color: #f9f9f9;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }
        .parameter {
            margin-bottom: 12px;
        }
        .tag {
            display: inline-block;
            background-color: #3498db;
            color: white;
            padding: 3px 10px;
            border-radius: 15px;
            margin-right: 5px;
            font-size: 0.9em;
        }
        .result {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 15px;
            font-weight: bold;
        }
        .result-1 {
            background-color: #2ecc71;
            color: white;
        }
        .result-0 {
            background-color: #e74c3c;
            color: white;
        }
        details {
            border: 1px solid #aaa;
            border-radius: 4px;
            padding: 0.5em 0.5em 0;
        }
        summary {
            font-weight: bold;
            margin: -0.5em -0.5em 0;
            padding: 0.5em;
        }
        details[open] {
            padding: 0.5em;
        }
        details[open] summary {
            border-bottom: 1px solid #aaa;
            margin-bottom: 0.5em;
        }
        pre {
            overflow: auto;
        }
    </style>
</head>
<body>
    ${runs.map((run, index) => {
        const { llm, judge, tasks } = run;
        return `
        <h1>Run #${index + 1}</h1>
        <div class="section">
            <h2>LLM Parameters</h2>
            <div class="parameter"><strong>Model:</strong> ${llm.llm.model}</div>
            <div class="parameter"><strong>API URL:</strong> ${llm.llm.apiUrl}</div>
            <div class="parameter"><strong>Max Tokens:</strong> ${llm.llm.max_tokens}</div>
            <div class="parameter"><strong>Temperature:</strong> ${llm.llm.temperature}</div>
        </div>
        <div class="section">
            <h2>Judge Parameters</h2>
            <div class="parameter"><strong>Model:</strong> ${judge.llm.model}</div>
            <div class="parameter"><strong>API URL:</strong> ${judge.llm.apiUrl}</div>
            <div class="parameter"><strong>Temperature:</strong> ${judge.llm.temperature}</div>
        </div>
        <h2>Tasks</h2>
        ${tasks.map((task, index) => `
        <div class="task">
            <h3>Task ${index + 1}</h3>
            <div class="parameter"><strong>Question:</strong> ${task.question}</div>
            <div class="parameter"><strong>Answer:</strong> ${task.answer}</div>
            <div class="parameter"><strong>Criteria:</strong>
                <ul>
                    ${Object.entries(task.criteria).map(([key, value]) => {
                        const result = task.results[key];
                        const prompt = prompts[judge.llm.prompt ?? 'default'] ?? prompts.default;
                        const judgePrompt = prompt({ question: task.question, answer: task.answer, criteria: value })
                        return `
                    <li>
                        <strong>${key}:</strong>
                        <span class="result result-${result}">${result}</span>&nbsp;
                        <span class="value">${value}</span>
                        <details>
                            <summary>Prompt</summary>
                            <pre>${escapeHTML(judgePrompt)}</pre>
                        </details>
                    </li>
                `.trim();
                    })}
                </ul>
            </div>
            <div class="parameter"><strong>Tags:</strong> ${task.tags.map((tag: string) => `<span class="tag">${tag}</span>`).join(' ')}</div>
            <div class="parameter"><strong>Time:</strong> ${task.time} ms</div>
        </div>
        `.trim()).join('')}`;
    })}
</body>
</html>
    `;
    return htmlContent;
}

function escapeHTML(str: string) {
    return str.replace(/[&<>]/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
    }[char]));
}