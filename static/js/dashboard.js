let verdictChart; // Global variable so we can refresh the chart cleanly

document.addEventListener("DOMContentLoaded", fetchDashboardData);

async function fetchDashboardData() {
    try {
        const response = await fetch('/api/dashboard_data');
        const data = await response.json();
        
        if (data.error) {
            window.location.href = '/login'; // Redirect if not logged in
            return;
        }
        
        populateDashboard(data);
    } catch (error) {
        console.error("Error fetching dashboard data:", error);
    }
}

function populateDashboard(data) {
    const total = data.length;
    let totalScore = 0;
    let aiCount = 0;
    let mixedCount = 0;
    let humanCount = 0;

    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = ''; // Clear existing table

    data.forEach(record => {
        totalScore += record.ai_score;
        
        // Count for charts
        if (record.verdict === "AI Generated") aiCount++;
        else if (record.verdict === "Mixed") mixedCount++;
        else humanCount++;

        // Determine badge color
        let badgeColor = record.ai_score > 60 ? 'var(--danger)' : (record.ai_score > 30 ? 'var(--accent-dark)' : 'var(--success)');

        // Build Table Row with the OVERRIDE Button
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${record.timestamp}</td>
            <td><b>${record.student_name}</b></td>
            <td>${record.matric_no}</td>
            <td><span style="background: ${badgeColor}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${record.ai_score}%</span></td>
            <td>${record.verdict}</td>
            <td>
                <button onclick="deleteRecord(${record.id}, '${record.matric_no}')" style="background: var(--danger); color: white; border: none; padding: 6px 12px; border-radius: 5px; cursor: pointer; font-weight: bold;">
                    🗑️ Override
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // Update Top Summary Banners
    document.getElementById('totalSubmissions').innerText = total;
    if (total > 0) {
        document.getElementById('avgProbability').innerText = Math.round(totalScore / total) + "%";
        document.getElementById('globalUsage').innerText = Math.round((aiCount / total) * 100) + "%";
        
        // Update stats text
        document.getElementById('statsText').innerHTML = `
            🔴 High AI Suspicions: <b>${aiCount}</b><br>
            🟡 Mixed Content: <b>${mixedCount}</b><br>
            🟢 Human Written: <b>${humanCount}</b>
        `;
    }

    // --- DRAW THE BAR CHART ---
    const ctx = document.getElementById('verdictChart').getContext('2d');
    
    if (verdictChart) {
        verdictChart.destroy(); // Destroy old chart before drawing new one
    }

    verdictChart = new Chart(ctx, {
        type: 'bar', // Changed from doughnut to bar!
        data: {
            labels: ['AI Generated', 'Mixed Content', 'Human Written'],
            datasets: [{
                label: 'Number of Students',
                data: [aiCount, mixedCount, humanCount],
                backgroundColor: ['#ef4444', '#f59e0b', '#10b981'], // Red, Yellow, Green
                borderRadius: 5 // Gives the bars nice rounded corners
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false } // Hide legend since labels are on the bottom
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1 // Forces the graph to only show whole numbers
                    }
                }
            }
        }
    });
}

// THE NEW OVERRIDE FUNCTION
async function deleteRecord(id, matricNo) {
    const confirmDelete = confirm(`WARNING: Are you sure you want to delete the record for ${matricNo}? \n\nThis will completely erase their score and allow them to upload a new project.`);
    
    if (confirmDelete) {
        try {
            const response = await fetch('/delete/' + id, { method: 'POST' });
            const result = await response.json();
            
            if (result.success) {
                alert(`Override successful! ${matricNo} has been cleared from the database.`);
                fetchDashboardData(); // Refreshes the table and charts instantly!
            } else {
                alert("Error: " + result.error);
            }
        } catch (error) {
            console.error("Delete error:", error);
            alert("Failed to connect to the server.");
        }
    }
}