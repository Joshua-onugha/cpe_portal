async function analyze() {
    const studentName = document.getElementById('studentName').value;
    const matricNo = document.getElementById('matricNo').value;
    const fileInput = document.getElementById('fileInput');
    const btn = document.getElementById('btn');
    const resultsDiv = document.getElementById('results');
    const verdictText = document.getElementById('verdict');

    // 1. Basic Frontend Validation
    if (!studentName || !matricNo) {
        alert("Please enter both your Name and Matriculation Number.");
        return;
    }

    if (fileInput.files.length === 0) {
        alert("Please upload your Project PDF file.");
        return;
    }

    // 2. Visual Loading State
    btn.innerText = "Scanning Project... Please wait";
    btn.disabled = true;
    btn.style.opacity = "0.7";
    resultsDiv.style.display = "none";

    // 3. Prepare data for Python
    const formData = new FormData();
    formData.append('studentName', studentName);
    formData.append('matricNo', matricNo);
    formData.append('file', fileInput.files[0]);

    try {
        // Send to Backend
        const response = await fetch('/analyze', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        // 4. THE GATEKEEPER CATCHER (Checks for the 400 error)
        if (!response.ok || data.error) {
            alert(data.error); // This pops up the "Submission Blocked" warning
            
            // Reset the button so they can fix the error and try again
            btn.innerText = "Scan Project";
            btn.disabled = false;
            btn.style.opacity = "1";
            return; // Stops the function immediately
        }

        // 5. Success! Populate the Results UI
        document.getElementById('scoreBox').innerText = data.score + "%";
        verdictText.innerText = data.verdict;
        document.getElementById('m-perp').innerText = data.perp;
        document.getElementById('m-burst').innerText = data.burst;
        document.getElementById('m-cons').innerText = data.cons + "%";
        
        // Color code the verdict box
        if(data.score > 60) {
            verdictText.style.color = "var(--danger)";
            document.getElementById('scoreBox').style.borderColor = "var(--danger)";
        } else if(data.score > 30) {
            verdictText.style.color = "var(--accent-dark)";
            document.getElementById('scoreBox').style.borderColor = "var(--accent-dark)";
        } else {
            verdictText.style.color = "var(--success)";
            document.getElementById('scoreBox').style.borderColor = "var(--success)";
        }

        // Generate dynamic link for printing the report
        document.getElementById('downloadLink').href = "/report/" + data.report_id;

        // Reveal the hidden results div
        resultsDiv.style.display = "block";

    } catch (error) {
        console.error("Error:", error);
        alert("Server error. Ensure the backend is running properly.");
    } finally {
        // Always reset button state when done
        btn.innerText = "Scan Project";
        btn.disabled = false;
        btn.style.opacity = "1";
    }
}