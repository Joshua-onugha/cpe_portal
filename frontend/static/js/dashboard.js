let verdictChart;

document.addEventListener("DOMContentLoaded", () => {
    // Redirect to login if no token
    if (!localStorage.getItem("token")) {
        window.location.href = "/login.html";
        return;
    }
    fetchDashboardData();
});

function authHeaders() {
    return {
        Authorization: `Bearer ${localStorage.getItem("token")}`,
    };
}

async function fetchDashboardData() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/dashboard_data`, {
            headers: authHeaders(),
        });

        if (response.status === 401 || response.status === 422) {
            localStorage.removeItem("token");
            window.location.href = "/login.html";
            return;
        }

        const data = await response.json();

        if (data.error) {
            window.location.href = "/login.html";
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

    const tbody = document.getElementById("tableBody");
    tbody.innerHTML = "";

    data.forEach((record) => {
        totalScore += record.ai_score;

        if (record.verdict === "AI Generated") aiCount++;
        else if (record.verdict === "Mixed") mixedCount++;
        else humanCount++;

        let badgeColor =
            record.ai_score > 60
                ? "var(--danger)"
                : record.ai_score > 30
                ? "var(--accent-dark)"
                : "var(--success)";

        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${record.timestamp}</td>
            <td><b>${record.student_name}</b></td>
            <td>${record.matric_no}</td>
            <td><span style="background: ${badgeColor}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;">${record.ai_score}%</span></td>
            <td>${record.verdict}</td>
            <td>
                <button onclick="deleteRecord(${record.id}, '${record.matric_no}')" style="background: var(--danger); color: white; border: none; padding: 6px 12px; border-radius: 5px; cursor: pointer; font-weight: bold;">
                    &#x1F5D1;&#xFE0F; Override
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // Summary banners
    document.getElementById("totalSubmissions").textContent = total;
    if (total > 0) {
        document.getElementById("avgProbability").textContent =
            Math.round(totalScore / total) + "%";
        document.getElementById("globalUsage").textContent =
            Math.round((aiCount / total) * 100) + "%";
        document.getElementById("statsText").innerHTML = `
            &#x1F534; High AI Suspicions: <b>${aiCount}</b><br>
            &#x1F7E1; Mixed Content: <b>${mixedCount}</b><br>
            &#x1F7E2; Human Written: <b>${humanCount}</b>
        `;
    }

    // Bar chart
    const ctx = document.getElementById("verdictChart").getContext("2d");
    if (verdictChart) verdictChart.destroy();

    verdictChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["AI Generated", "Mixed Content", "Human Written"],
            datasets: [
                {
                    label: "Number of Students",
                    data: [aiCount, mixedCount, humanCount],
                    backgroundColor: ["#ef4444", "#f59e0b", "#10b981"],
                    borderRadius: 5,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
        },
    });
}

async function deleteRecord(id, matricNo) {
    const confirmed = confirm(
        `WARNING: Are you sure you want to delete the record for ${matricNo}?\n\nThis will completely erase their score and allow them to upload a new project.`
    );

    if (!confirmed) return;

    try {
        const response = await fetch(`${BACKEND_URL}/api/delete/${id}`, {
            method: "POST",
            headers: authHeaders(),
        });
        const result = await response.json();

        if (result.success) {
            alert(`Override successful! ${matricNo} has been cleared.`);
            fetchDashboardData();
        } else {
            alert("Error: " + result.error);
        }
    } catch (error) {
        console.error("Delete error:", error);
        alert("Failed to connect to the server.");
    }
}

function logout() {
    localStorage.removeItem("token");
    window.location.href = "/login.html";
}
