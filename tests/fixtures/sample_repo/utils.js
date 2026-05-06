/**
 * Utility functions for the application.
 */

function formatDate(date) {
    return date.toISOString().split('T')[0];
}

function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

class StringHelper {
    static capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    static truncate(str, maxLength) {
        if (str.length <= maxLength) return str;
        return str.slice(0, maxLength) + '...';
    }
}

export { formatDate, validateEmail, StringHelper };
