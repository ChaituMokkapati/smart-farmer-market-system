const express = require("express");
const bodyParser = require("body-parser");
const cors = require("cors");
const fast2sms = require("fast2sms");

const app = express();

app.use(cors());
app.use(bodyParser.json());

let otpStore = {};

app.post("/send-otp", async (req, res) => {

    const phone = req.body.phone;

    const otp = Math.floor(100000 + Math.random() * 900000);

    otpStore[phone] = otp;

    const options = {
        authorization: "YOUR_FAST2SMS_API_KEY",
        message: `Your OTP is ${otp}`,
        numbers: [phone]
    };

    try {
        await fast2sms.sendMessage(options);
        res.send({ success: true, message: "OTP Sent" });
    } catch (error) {
        res.send({ success: false, message: "Error sending OTP" });
    }

});

app.post("/verify-otp", (req, res) => {

    const phone = req.body.phone;
    const otp = req.body.otp;

    if (otpStore[phone] == otp) {
        res.send({ success: true, message: "OTP Verified" });
    } else {
        res.send({ success: false, message: "Invalid OTP" });
    }

})

// Changed port to 5001 to avoid conflict with Flask (which usually runs on 5000)
try {
    app.listen(5001, () => {
        console.log("Node.js OTP Server running on port 5001");
    });
} catch (err) {
    console.error("Failed to start server:", err);
    process.exit(1);
}

process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});

process.on('uncaughtException', (err) => {
    console.error('Uncaught Exception:', err);
});
