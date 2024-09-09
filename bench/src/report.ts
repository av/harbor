export const template = (data: unknown) => `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task Results Report</title>
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
    <h1>Task Results Report</h1>
    <div class="summary">
        <h2>Summary</h2>
        <p>Total tasks: <span id="totalTasks"></span></p>
        <p>Overall success rate: <span id="overallSuccessRate"></span>%</p>
        <p>Average task duration: <span id="averageTaskDuration"></span> ms</p>
        <p>Task duration range: <span id="minTaskDuration"></span> ms - <span id="maxTaskDuration"></span> ms</p>
    </div>
    <h2>Results by Dimension</h2>
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

