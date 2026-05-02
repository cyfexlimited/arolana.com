// Notification sound
function playNotificationSound() {
    const audio = new Audio('/static/sounds/notification.mp3');
    audio.play().catch(e => console.log('Audio play failed:', e));
}

// Show toast notification
function showToastNotification(title, message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    
    const toast = document.createElement('div');
    toast.className = `toast-notification bg-white rounded-lg shadow-xl p-4 mb-3 border-l-4 ${
        type === 'success' ? 'border-green-500' : type === 'error' ? 'border-red-500' : 'border-blue-500'
    }`;
    toast.innerHTML = `
        <div class="flex items-center gap-3">
            <div class="${type === 'success' ? 'text-green-500' : type === 'error' ? 'text-red-500' : 'text-blue-500'}">
                <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-bell'} text-xl"></i>
            </div>
            <div class="flex-1">
                <p class="font-semibold text-gray-800">${title}</p>
                <p class="text-gray-600 text-sm">${message}</p>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" class="text-gray-400 hover:text-gray-600">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
    
    // Play sound
    playNotificationSound();
}
