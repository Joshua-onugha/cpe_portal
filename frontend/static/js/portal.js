async function analyze() {
    const studentName = document.getElementById("studentName").value;
    const matricNo = document.getElementById("matricNo").value;
    const fileInput = document.getElementById("fileInput");
    const btn = document.getElementById("btn");
    const resultsDiv = document.getElementById("results");
    const verdictText = document.getElementById("verdict");

    if (!studentName || !matricNo) {
        alert("Please enter both your Name and Matriculation Number.");
        return;
    }

    if (fileInput.files.length === 0) {
        alert("Please upload your Project file (PDF or DOCX).");
        return;
    }

    btn.textContent = "Scanning Project... Please wait";
    btn.disabled = true;
    btn.style.opacity = "0.7";
    resultsDiv.style.display = "none";

    const formData = new FormData();
    formData.append("studentName", studentName);
    formData.append("matricNo", matricNo);
    formData.append("file", fileInput.files[0]);

    try {
        const response = await fetch(`${BACKEND_URL}/api/analyze`, {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            alert(data.error);
            return;
        }

        // Populate results
        document.getElementById("scoreBox").textContent = data.score + "%";
        verdictText.textContent = data.verdict;
        document.getElementById("m-perp").textContent = data.perp;
        document.getElementById("m-burst").textContent = data.burst;
        document.getElementById("m-cons").textContent = data.cons + "%";

        // Color code
        if (data.score > 60) {
            verdictText.style.color = "var(--danger)";
            document.getElementById("scoreBox").style.borderColor = "var(--danger)";
        } else if (data.score > 30) {
            verdictText.style.color = "var(--accent-dark)";
            document.getElementById("scoreBox").style.borderColor = "var(--accent-dark)";
        } else {
            verdictText.style.color = "var(--success)";
            document.getElementById("scoreBox").style.borderColor = "var(--success)";
        }

        // Link to report page
        document.getElementById("downloadLink").href = `/report.html?id=${data.report_id}`;

        resultsDiv.style.display = "block";
    } catch (error) {
        console.error("Error:", error);
        alert("Server error. Ensure the backend is running and accessible.");
    } finally {
        btn.textContent = "Scan Project";
        btn.disabled = false;
        btn.style.opacity = "1";
    }
}
